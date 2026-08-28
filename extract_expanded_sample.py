import argparse
import json
from dataclasses import asdict

from truper_catalog.extractor import HttpConfig, TruperExtractor
from truper_catalog.storage import load_csv, save_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Muestra paginada y reanudable del catálogo Truper")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--output", default="output/truper_expanded_sample.csv")
    parser.add_argument("--checkpoint", default="state/truper_checkpoint.json")
    parser.add_argument("--errors", default="logs/truper_errors.jsonl")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--fresh", action="store_true", help="Ignora el CSV existente")
    args = parser.parse_args()

    terms = args.term or ["truper"]
    config = HttpConfig(timeout=args.timeout, delay=args.delay, retries=args.retries)
    extractor = TruperExtractor(config=config)
    existing = [] if args.fresh else load_csv(args.output)
    products, stats = extractor.enumerate_search(
        terms, args.limit, args.checkpoint, args.errors, seed=existing,
        ignore_checkpoint=args.fresh,
    )
    save_csv(products, args.output)
    print(json.dumps(asdict(stats), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
