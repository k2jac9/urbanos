"""STRETCH GOAL — QLoRA fine-tune of Nemotron Nano for Toronto address/entity resolution.

The hard, defensible problem in this project is matching messy municipal address
strings ("100 Queen St W" == "100 QUEEN STREET WEST" == "100 Queen St. West, Toronto").
A small QLoRA adapter teaches the model that mapping. This is a STRETCH GOAL: only
attempt it if the core demo is solid — training can eat the weekend.

Runs on the ASUS Ascent GX10 (GB10 GPU). Heavy deps (unsloth/trl/peft/torch) are
imported inside main() so this file stays importable on a laptop without a GPU.

    pip install unsloth trl peft datasets        # on the GX10 (ARM64 + CUDA)
    python scripts/finetune_address_resolution.py --data fixtures/address_resolution.sample.jsonl

Serve the resulting adapter with vLLM:
    vllm serve nvidia/nemotron-3-nano --enable-lora \
        --lora-modules toronto-addr=./out/toronto-addr-lora
Then set LLM_MODEL=toronto-addr so /analyze uses the fine-tuned adapter.
"""
from __future__ import annotations

import argparse

SYSTEM = "Normalize the Toronto address to canonical form: '<NUM> <NAME> <TYPE> <DIR>', uppercase."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="fixtures/address_resolution.sample.jsonl")
    parser.add_argument("--base-model", default="nvidia/nemotron-3-nano")
    parser.add_argument("--out", default="./out/toronto-addr-lora")
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()

    # Heavy imports only when actually training (GX10 only).
    import json

    from datasets import Dataset  # noqa: F401
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    rows = [json.loads(line) for line in open(args.data) if line.strip()]
    examples = [
        {
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": r["raw"]},
                {"role": "assistant", "content": r["canonical"]},
            ]
        }
        for r in rows
    ]

    model, tokenizer = FastLanguageModel.from_pretrained(
        args.base_model, max_seq_length=512, load_in_4bit=True
    )
    model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=16)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=Dataset.from_list(examples),
        args=SFTConfig(output_dir=args.out, num_train_epochs=args.epochs, per_device_train_batch_size=2),
    )
    trainer.train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"LoRA adapter saved to {args.out}")


if __name__ == "__main__":
    main()
