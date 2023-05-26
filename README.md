To install necessary libraries on a freshly installed Ubuntu Server system, follow these steps:

1. Install Python 3 and pip:

```bash
sudo apt update
sudo apt install -y python3 python3-pip
```

2. Install the required Python libraries:

```bash
pip3 install mapproxy owslib click rasterio
```

3. Install GDAL (required for rasterio):

```bash
sudo apt install -y gdal-bin libgdal-dev
export CPLUS_INCLUDE_PATH=/usr/include/gdal
export C_INCLUDE_PATH=/usr/include/gdal
pip3 install GDAL==$(gdal-config --version)
```

python3 wmts_to_geotiff.py -u "https://services.arcgisonline.com/arcgis/rest/services/Demographics/USA_Daytime_Population/MapServer/WMTS" -l "0" -z 5 -b -123.42 37.54 -123.32 37.64