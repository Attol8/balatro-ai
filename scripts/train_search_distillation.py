#!/usr/bin/env python3
"""Distill public search sibling utilities into the existing policy/value model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from balatro_ai_v2.public_model import PublicModelConfig, PublicRecurrentPolicyValue, save_public_model
from balatro_ai_v2.search_distillation import read_comparisons, distillation_loss


def main() -> None:
    args = build_parser().parse_args()
    if min(args.epochs, args.batch_size, args.learning_rate) <= 0:
        raise SystemExit("epochs, batch size, and learning rate must be positive")
    torch.manual_seed(args.training_seed)
    model = PublicRecurrentPolicyValue(PublicModelConfig(hidden_size=args.hidden_size)).to(args.device)
    comparisons = read_comparisons(args.input_jsonl)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    losses: list[dict[str, float]] = []
    model.train()
    for _ in range(args.epochs):
        order = torch.randperm(len(comparisons)).tolist()
        epoch: list[dict[str, float]] = []
        for start in range(0, len(order), args.batch_size):
            batch = tuple(comparisons[index] for index in order[start : start + args.batch_size])
            loss, metrics = distillation_loss(model, batch, margin=args.margin)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_gradient_norm)
            optimizer.step()
            epoch.append(metrics)
        losses.append({key: sum(row[key] for row in epoch) / len(epoch) for key in epoch[0]})
    digest = save_public_model(args.output_model, model)
    report = {
        "candidate_only": True,
        "dataset": str(args.input_jsonl),
        "comparisons": len(comparisons),
        "model_digest": digest,
        "epochs": args.epochs,
        "losses": losses,
    }
    print(json.dumps(report, sort_keys=True))
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--training-seed", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--max-gradient-norm", type=float, default=0.5)
    parser.add_argument("--margin", type=float, default=0.05)
    parser.add_argument("--device", default="cpu")
    return parser


if __name__ == "__main__":
    main()
