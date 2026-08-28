import argparse

from truper_catalog.extractor import TruperExtractor
from truper_catalog.storage import save_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba pequeña del catálogo público de Truper")
    parser.add_argument("--term", default="martillo", help="Código, clave o descripción")
    parser.add_argument("--limit", type=int, default=5, help="Máximo de productos (predeterminado: 5)")
    parser.add_argument("--pause", type=float, default=1.0, help="Pausa mínima entre peticiones")
    parser.add_argument("--output", default="output/truper_sample.csv")
    args = parser.parse_args()

    extractor = TruperExtractor(pause_seconds=args.pause)
    products = extractor.search(args.term, limit=args.limit)
    count = save_csv(products, args.output)
    print(f"Guardados {count} productos únicos en {args.output}")
    for product in products:
        print(product)


if __name__ == "__main__":
    main()

