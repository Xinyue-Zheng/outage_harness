import sys

import requests


BASE_URL = ""
def query_point_coverage(
    lat: str,
    lon:str,
    r:str,
    token:str,
):
    url = f"{BASE_URL}/{lat}/{lon}?radius={int(r)}"
    headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
}
    response = requests.get(url, headers=headers, timeout=(15,300))
    response.raise_for_status()
    data = response.json()
    data = data['array']
    return data
    