import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.merge import merge
from rasterio.transform import from_origin

def reproject_raster(src_path, dst_path, target_crs="EPSG:4326", resampling=Resampling.bilinear):
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds)
        kwargs = src.meta.copy()
        kwargs.update({
            "crs": target_crs,
            "transform": transform,
            "width": width,
            "height": height
        })
        with rasterio.open(dst_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=resampling
                )
    print(f"✅ Reprojected → {dst_path}")

# def resample_raster(src_path, dst_path, new_resolution, resampling=Resampling.bilinear):
#     with rasterio.open(src_path) as src:
#         scale = src.res[0] / new_resolution
#         new_height = int(src.height * scale)
#         new_width = int(src.width * scale)
#         kwargs = src.meta.copy()
#         kwargs.update({
#             "height": new_height,
#             "width": new_width,
#             "transform": src.transform * src.transform.scale(
#                 (src.width / new_width),
#                 (src.height / new_height)
#             )
#         })
#         data = src.read(
#             out_shape=(src.count, new_height, new_width),
#             resampling=resampling
#         )
#         with rasterio.open(dst_path, "w", **kwargs) as dst:
#             dst.write(data)
#     print(f"✅ Resampled → {dst_path}")


def resample_raster(src_path, dst_path, new_resolution=10):
    """Resample raster to a new resolution (handles missing transform)."""
    with rasterio.open(src_path) as src:
        # 🧭 Fix missing transform (if pixel size = 0)
        transform = src.transform
        if abs(transform.a) < 1e-6 or abs(transform.e) < 1e-6:
            print("⚠️ Invalid transform detected — assigning default pixel size.")
            transform = from_origin(src.bounds.left, src.bounds.top, 30, 30)  # assume ~30m Landsat

        # 🧮 Compute new transform safely
        transform_new, width_new, height_new = calculate_default_transform(
            src.crs,
            src.crs,
            src.width,
            src.height,
            *src.bounds,
            resolution=new_resolution
        )

        kwargs = src.meta.copy()
        kwargs.update({
            "crs": src.crs,
            "transform": transform_new,
            "width": width_new,
            "height": height_new
        })

        with rasterio.open(dst_path, "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=transform,
                    src_crs=src.crs,
                    dst_transform=transform_new,
                    dst_crs=src.crs,
                    resampling=Resampling.bilinear
                )

    print(f"✅ Resampled → {dst_path}")


def mosaic_rasters(input_paths, output_path):
    srcs = [rasterio.open(p) for p in input_paths]
    mosaic, out_trans = merge(srcs)
    out_meta = srcs[0].meta.copy()
    out_meta.update({
        "height": mosaic.shape[1],
        "width": mosaic.shape[2],
        "transform": out_trans
    })
    with rasterio.open(output_path, "w", **out_meta) as dest:
        dest.write(mosaic)
    print(f"✅ Mosaic saved → {output_path}")
