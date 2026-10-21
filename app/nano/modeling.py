# منقول دون تعديل من voyageai/voyage-4-nano على Hugging Face،
# المراجعة 433ece5e27a1611e9360dd7134ecaaf79fb3681d، الملف modeling_qwen3_bidirectional.py.
# الرخصة Apache 2.0، والنص الكامل وملاحظة الحقوق في LICENSE.txt و NOTICE.txt
# في هذا المجلد. نقلناه إلى المستودع كي لا يُنفَّذ كود يُنزَّل من الشبكة
# عند التشغيل (trust_remote_code).
import inspect
from typing import Callable
import torch
import torch.nn as nn
from transformers import PreTrainedModel, Qwen3Config, Qwen3Model
from transformers.cache_utils import Cache
from transformers.masking_utils import create_causal_mask
from transformers.modeling_outputs import BaseModelOutputWithPooling
from transformers.processing_utils import Unpack
from transformers.utils import TransformersKwargs

# transformers 5.2 renamed `input_embeds` -> `inputs_embeds` and later v5 releases dropped `cache_position`
_CAUSAL_MASK_PARAMS = inspect.signature(create_causal_mask).parameters


# From modeling_t5gemma.py
def bidirectional_mask_function(attention_mask: torch.Tensor | None) -> Callable:
    """
    This creates bidirectional attention mask.
    """

    def inner_mask(batch_idx: int, head_idx: int, q_idx: int, kv_idx: int) -> bool:
        if attention_mask is None:
            return torch.ones((), dtype=torch.bool)
        return attention_mask[batch_idx, kv_idx].to(torch.bool)

    return inner_mask


class Qwen3BidirectionalModel(PreTrainedModel):
    config_class = Qwen3Config
    _supports_flash_attn = True
    _supports_sdpa = True

    def __init__(self, config):
        super().__init__(config)
        self.model = Qwen3Model(config)
        self.linear = nn.Linear(config.hidden_size, config.num_labels, bias=False)
        self.post_init()

    def post_init(self):
        super().post_init()
        # Override to set all layers to non-causal attention. This'll work with attn_implementation="flash_attention_2" or "sdpa"
        for layer in self.model.layers:
            layer.self_attn.is_causal = False

    def forward(
        self,
        input_ids: torch.LongTensor | None = None,
        attention_mask: torch.Tensor | None = None,
        position_ids: torch.LongTensor | None = None,
        past_key_values: Cache | None = None,
        inputs_embeds: torch.FloatTensor | None = None,
        use_cache: bool | None = None,
        cache_position: torch.LongTensor | None = None,
        **kwargs: Unpack[TransformersKwargs],
    ) -> BaseModelOutputWithPooling:
        if inputs_embeds is None:
            inputs_embeds = self.model.embed_tokens(input_ids)
            input_ids = None

        mask_kwargs = {
            "config": self.config,
            "attention_mask": attention_mask,
            "past_key_values": None,
            "position_ids": position_ids,
            "or_mask_function": bidirectional_mask_function(attention_mask),
        }
        if "inputs_embeds" in _CAUSAL_MASK_PARAMS:
            mask_kwargs["inputs_embeds"] = inputs_embeds
        else:
            mask_kwargs["input_embeds"] = inputs_embeds
        if "cache_position" in _CAUSAL_MASK_PARAMS:
            # We construct a dummy tensor imitating initial positions
            mask_kwargs["cache_position"] = torch.arange(
                inputs_embeds.shape[1], device=inputs_embeds.device, dtype=torch.long
            )
        attention_mask = {"full_attention": create_causal_mask(**mask_kwargs)}

        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_values=past_key_values,
            inputs_embeds=inputs_embeds,
            use_cache=use_cache,
            cache_position=cache_position,
            **kwargs,
        )
        outputs.last_hidden_state = self.linear(outputs.last_hidden_state)
        return outputs
