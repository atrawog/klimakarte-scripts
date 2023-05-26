#!/usr/bin/env python3

import click
from mapproxy.config.config import load_default_config
from mapproxy.config.loader import ProxyConfiguration
from mapproxy.seed.util import extent_to_grid_coverage, merge_coverage
from mapproxy.seed.seeder import seed
from owslib.wmts import WebMapTileService
from mapproxy.grid import TileGrid
import yaml
import sys
import os
import logging
import rasterio
from rasterio.vrt import WarpedVRT
import numpy as np

logging.basicConfig(level=logging.INFO)

@click.command()
@click.option('-u', '--wmts-url', help='The WMTS URL from which the layer definition will be fetched.', required=True)
@click.option('-l', '--layer-name', help='The layer name for which the configuration should be generated.', required=True)
@click.option('-z', '--zoom-level', type=int, help='The zoom level of the layer to be turned into a single GeoTIFF.', required=True)
@click.option('-b', '--bbox', nargs=4, type=float, help='The bounding box for the GeoTIFF in WGS84 coordinates (minx, miny, maxx, maxy).', required=True)
@click.option('-c', '--mapproxy-config', default='mapproxy_config.yaml', help='Generated MapProxy configuration file name.')
@click.option('-o', '--output', default='output.gtiff', help='The name of the resulting GeoTIFF file.')
@click.option('-s', '--srs', default='EPSG:3857', help='The SRS definition for the output GeoTIFF (e.g., EPSG:3857 or EPSG:4326). Default is Web Mercator.')
def main(wmts_url, layer_name, zoom_level, bbox, mapproxy_config, output, srs):
    wmts = WebMapTileService(wmts_url)
    if layer_name not in wmts.contents:
        logging.error(f'Layer "{layer_name}" not found in provided WMTS service')
        sys.exit(1)

    wmts_layer = wmts[layer_name]
    wmts_tile_matrix_set = wmts_layer.tilematrixsets[0]
    wmts_tile_matrix_set_obj = wmts.tilematrixsets[wmts_tile_matrix_set]

    user_bbox_str = ' '.join(str(b) for b in bbox)

    mapproxy_config_template = '''
services:
  wmts:
    md:
      title: WMTS Layer Proxy

layers:
  - name: {layer_name}
    title: {title}
    sources: [{layer_name}_cache]

caches:
  {layer_name}_cache:
    grids: [{tile_matrix_set_id}]
    sources: [{layer_name}_source]

sources:
  {layer_name}_source:
    type: tile
    grid: {tile_matrix_set_id}
    url: {wmts_url}
    extension: {format_extension}
    wmts_layer: {layer_name}
    wmts_tile_matrix_set: {tile_matrix_set_id}
    coverage:
      bbox: {user_bbox}
      srs: '{srs}'

grids:
  {tile_matrix_set_id}:
    srs: '{srs}'
    origin: 'ul'
    bbox: {bbox}
    tile_size: [256, 256]
    res_factor: 2
    resolutions:
{resolutions_str}
    '''
    resolutions_str = '      - ' + '\n      - '.join(str(res) for res in wmts_tile_matrix_set_obj.resolutions[:zoom_level + 1])

    mapproxy_config_data = mapproxy_config_template.format(
        layer_name=layer_name,
        title=wmts_layer.title,
        tile_matrix_set_id=wmts_tile_matrix_set_obj.title,
        wmts_url=wmts_url,
        format_extension=wmts_layer.formats[0].split('/')[-1],
        bbox=wmts_tile_matrix_set_obj.bboxWGS84,
        user_bbox=user_bbox_str,
        resolutions_str=resolutions_str,
        srs=srs,
    )

    with open(mapproxy_config, 'w') as f:
        f.write(mapproxy_config_data)

    config_dict = load_default_config(None, None, base_conf=None)
    with open(mapproxy_config, 'rt') as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
    configuration = ProxyConfiguration(config, seed=True, renderd=False, config_file=mapproxy_config)
    seed_conf = configuration.seed_conf

    wgs84_bbox = wmts_tile_matrix_set_obj.bboxWGS84
    grid = TileGrid(seed_conf.caches[layer_name]['grid'])

    coverage = extent_to_grid_coverage(wgs84_bbox, grid, zoom_level)
    task = (layer_name, srs, zoom_level, False)

    coverage_information = {
        'cache_name': task[0],
        'srs': task[1],
        'min_level': task[2],
        'max_level': task[2],
        'dry_run': task[3],
    }

    seed_conf.coverage = merge_coverage(seed_conf.coverage, (coverage,), 'intersect', coverage_information)
    seed_config = {'seed_only': [{'cache_name': layer_name}], 'concurrency': 1}

    try:
        os.makedirs("cache_data", exist_ok=True)
        seed(seed_config, seed_conf)
        source_path = f"cache_data/{layer_name}_cache_{srs.replace(':', '')}/{zoom_level}"
        if not os.path.isdir(source_path):
            logging.error(f"No data found for layer {layer_name} at zoom level {zoom_level}")
            sys.exit(1)

        input_file_list = []
        for root, dirs, files in os.walk(source_path):
            for file in files:
                if file.endswith(f".{wmts_layer.formats[0].split('/')[-1]}"):
                    input_file_list.append(os.path.join(root, file))

        with rasterio.open(input_file_list[0]) as src:
            meta = src.meta.copy()

        with rasterio.open(output, 'w', **meta) as mosaic:
            for input_file in input_file_list:
                with rasterio.open(input_file) as src:
                    with WarpedVRT(src, src_crs=src.crs, dst_crs=srs) as vrt:
                        windows = [window for _, window in vrt.block_windows()]
                        for window in windows:
                            src_array = vrt.read(window=window)
                            mosaic.write(src_array, window=window)

        logging.info(f"GeoTIFF generated successfully. Output: {output}")

    except Exception as e:
        logging.error(f"Error during process: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
