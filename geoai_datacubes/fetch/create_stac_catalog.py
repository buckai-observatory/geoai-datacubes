# create_stac_catalog.py
import os
import pystac
from datetime import datetime

def create_stac_item(image_path, collection="Sentinel-2", output_dir="data/catalog"):
    os.makedirs(output_dir, exist_ok=True)

    # Basic metadata (replace with actual metadata if available)
    item = pystac.Item(
        id=os.path.basename(image_path).split(".")[0],
        geometry=None,
        bbox=None,
        datetime=datetime.utcnow(),
        properties={"mission": collection}
    )

    item.add_asset(
        "image",
        pystac.Asset(
            href=image_path,
            media_type="image/tiff; application=geotiff",
            roles=["data"],
            title=f"{collection} Tile"
        )
    )

    # Create catalog if not exists
    catalog_path = os.path.join(output_dir, "catalog.json")
    if os.path.exists(catalog_path):
        catalog = pystac.read_file(catalog_path)
    else:
        catalog = pystac.Catalog(id="geoai-datacubes-catalog",
                                 description="geoai-datacubes imagery catalog")

    catalog.add_item(item)
    catalog.normalize_and_save(output_dir, catalog_type=pystac.CatalogType.SELF_CONTAINED)

    print(f"✅ Added {image_path} to STAC catalog → {catalog_path}")


if __name__ == "__main__":
    import glob as _g; _t = sorted(_g.glob("data/*/*_full_size.tiff"))
    if not _t:
        raise FileNotFoundError("No <Mission>_full_size.tiff found in data/")
    image_path = _t[-1]
    create_stac_item(image_path)
