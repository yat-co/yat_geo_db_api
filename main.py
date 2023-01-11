from flask import Flask, request, make_response
from flask_cors import CORS

from yat_geo_db import GeoManager as GeoManagerImport

from decouple import config
import logging
import json
import numpy as np
from typing import Dict, List, Union

app = Flask(__name__)
cors = CORS(app, resources={r"/api/*": {"origins": "*"}})

# Logging
logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
logger = logging.getLogger(__name__)

fileHandler = logging.FileHandler("./logs/search.log")
fileHandler.setFormatter(logFormatter)
logger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)


def parse_bool(x: str, nullable: bool = True, default: bool = False):
	'''
    Parse Bool
	'''
	if isinstance(x, bool):
		return x
	if isinstance(x, (int, np.int8, np.int16, np.int32, np.int64)):
		x = int(x)
		return x > 0
	if isinstance(x, (float, np.float16, np.float32, np.float64)):
		x = float(x)
		return x > 0
	if isinstance(x, str):
		if x.lower() in ['yes', 'y', 'true', 't', '1']:
			return True
		if x.lower() in ['no', 'n', 'false', 'f', '0']:
			return False
	if nullable:
		return None

	return default


GeoManager = GeoManagerImport()
GeoManager.load_data(
    force_db_fetch=config('FORCE_DB_FETCH', cast=bool, default=True),
    cache_local=config('CACHE_LOCAL', cast=bool, default=True)
)


def json_response(data: Union[List, Dict] = {}, status: int = 200, headers: Dict = None):
    headers = headers or {}
    if 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json'

    return make_response(data, status, headers)


allowed_params = [
    'is_zip_code', 'is_aggregate', 'is_three_digit_zip_code', 'geo_type',
    'ref_data.country', 'ref_data.state_prov'
]
params_func = {
    'is_zip_code': lambda val: parse_bool(val),
    'is_aggregate': lambda val: parse_bool(val),
    'is_three_digit_zip_code': lambda val: parse_bool(val),
    'geo_type': lambda val: parse_bool(val),
    'ref_data.country': lambda val: str(val).upper() if len(str(val)) == 2 else None,
    'ref_data.state_prov': lambda val: str(val).upper() if len(str(val)) == 2 else None
}

def parse_params(query_params: Dict, *args, **kwargs):
    included_params = [param for param in query_params if param in allowed_params]
    if included_params != []:
        params = {}
        for included_param in included_params:
            val = query_params.get(included_param)
            val = params_func[included_param](val)
            if val is not None:
                params.update({included_param: val})
        if params != {}:
            return params
    return None

@app.route('/api/search/', methods=['GET', 'OPTIONS'])
def fuzzy_search():
    if request.method == 'GET':
        query_params = dict(request.args)
        search_param = query_params.get('q')
        num_results = query_params.get('num_results', 8) or 8
        callback = query_params.get('callback')

        if search_param is None:
            return json_response(
                data={"error": "Must provide query string `?q=<query string>`"},
                status=400
            )

        filters = parse_params(query_params=query_params)
        fuzzy_res = GeoManager.fuzzy_search(
            search_param, num_results=int(num_results), filters=filters
        )

        # Option to Include Reference Extra -> City, State, Zip, Country
        if query_params.get('include_ref') is not None:
            search_res = [
                {
                    'id': x.get('id'),
                    'name': x.get('value', ''),
                    'ref': x.get('extra', {}).get("ref_data", {}),
                    'shape_id': x.get('extra', {}).get("id", None)
                }
                for x in fuzzy_res
            ]
        else:
            search_res = [
                {
                    'id': x.get('id'),
                    'name': x.get('value', ''),
                    'shape_id': x.get('extra', {}).get("id", None)
                } for x in fuzzy_res
            ]

        if callback is not None:
            # Process Callback based API call, mostly for jQuery Autocomplete
            callback_res = f"{callback}({json.dumps(search_res)});"
            return make_response(callback_res, 200)

        # Process standard call returning JSON Array of results
        return json_response(data=search_res, status=200)

    return json_response(data={"heathly": True}, status=200)


@app.route('/api/fetch/', methods=['GET', 'OPTIONS'])
def fetch():
    if request.method == 'GET':
        query_params = dict(request.args)
        shape_id = query_params.get('shape_id')
        shape_ref_code = query_params.get('shape_ref_code')

        ref_result = None
        if shape_id is not None:
            ref_result = GeoManager.get_shape_by_id(int(shape_id))
        elif shape_ref_code is not None:
            ref_result = GeoManager.get_shape_by_ref_code(shape_ref_code.lower())

        # Not Found if not Valid Response Found or Requested
        if ref_result is None:
            return json_response(data={"error": "not found"}, status=404)

        return json_response(data=ref_result, status=200)

    return json_response(data={"heathly": True}, status=200)


@app.route('/api/radius/', methods=['GET', 'OPTIONS'])
def radius_search():
    if request.method == 'GET':
        query_params = dict(request.args)
        shape_id = query_params.get('shape_id')
        shape_ref_code = query_params.get('shape_ref_code')
        radius = int(query_params.get('radius', 50))
        country_exact = parse_bool(query_params.get('country_exact', False))

        # If shape id provided then covert to Reference Code
        if shape_id is not None:
            shape_ref_code = GeoManager.get_shape_ref_code(int(shape_id))

        # If radius is less than one fail
        if radius < 1:
            return json_response(
                data={"error": "radius must be greater than 1"}, status=404
            )

        # Handle Shape Not Found
        if shape_ref_code is None:
            return json_response(data={"error": "not found"}, status=404)

        # Perform Radius Search
        radius_result = GeoManager.radius_search(
            reference_code=shape_ref_code, radius=radius, country_exact=country_exact
        )

        # Not Found if not Valid Response Found or Requested
        if radius_result is None:
            return json_response(data={"error": "not found"}, status=404)

        return json_response(data=radius_result, status=200)

    return json_response(data={"heathly": True}, status=200)


if __name__ == "__main__":
    app.run(
        host=config("API_HOST", cast=str, default="0.0.0.0"),
        port=config("API_PORT", cast=int, default=80),
        debug=config("DEBUG", cast=bool, default=True)
    )
