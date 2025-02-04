
import json
import re
import threading
from flask import Flask, request, jsonify, Response
from urllib.parse import urlparse

# Load HAR file
with open("try.har", "r", encoding="utf-8") as f:
    har_data = json.load(f)

mock_responses = {}
domain_ports = {}
base_port = 5000  # Start assigning ports from 5000

# Process HAR entries safely
for entry in har_data["log"]["entries"]:
    request_url = entry["request"]["url"]
    parsed_url = urlparse(request_url)
    domain = parsed_url.netloc  # Extract domain

    # Assign unique ports to domains
    if domain not in domain_ports:
        domain_ports[domain] = base_port
        base_port += 1  # Increment port for the next domain

    port = domain_ports[domain]  # Get assigned port for this domain

    request_body = entry["request"].get("postData", {}).get("text", "{}")  # Get request body safely
    try:
        request_data = json.loads(request_body) if request_body.strip() else {}
    except json.JSONDecodeError:
        request_data = {}

    response_body = entry["response"]["content"].get("text", "").strip()
    response_mime_type = entry["response"]["content"].get("mimeType", "application/json")

    try:
        if response_mime_type.startswith("application/json"):
            response_data = json.loads(response_body) if response_body else {}
        else:
            response_data = response_body
    except json.JSONDecodeError:
        response_data = response_body

    request_headers = {header["name"].lower(): True for header in entry["request"]["headers"]}

    if port not in mock_responses:
        mock_responses[port] = []

    mock_responses[port].append({
        "request_pattern": request_data,
        "headers_pattern": request_headers,
        "response": response_data,
        "mime_type": response_mime_type
    })

# Function to match request pattern
def match_pattern(example_request, actual_request):
    for key, example_value in example_request.items():
        actual_value = actual_request.get(key)
        if isinstance(example_value, int) and isinstance(actual_value, int):
            if len(str(example_value)) == len(str(actual_value)):
                continue
            else:
                return False
        if isinstance(example_value, str) and re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", example_value):
            if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", actual_value):
                continue
            else:
                return False
        if actual_value != example_value:
            return False
    return True

# Function to match headers
def match_headers(expected_headers, actual_headers):
    actual_keys = {key.lower() for key in actual_headers.keys()}
    expected_keys = set(expected_headers.keys())
    return expected_keys.issubset(actual_keys)

# Function to create and run Flask servers
def create_mock_server(port, responses):
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    def mock_server(path):
        try:
            if request.method in ["POST", "PUT", "PATCH"]:
                if request.content_type == "application/json":
                    actual_request = request.get_json() or {}
                else:
                    actual_request = request.form.to_dict()
            else:
                actual_request = request.args.to_dict()

            actual_headers = request.headers

            for mock in responses:
                if match_pattern(mock["request_pattern"], actual_request) and match_headers(mock["headers_pattern"], actual_headers):
                    difference_map = {}
                    for key, example_value in mock["request_pattern"].items():
                        actual_value = actual_request.get(key)
                        if actual_value and actual_value != example_value:
                            difference_map[str(example_value)] = str(actual_value)

                    modified_response = mock["response"]
                    if isinstance(modified_response, dict):
                        response_text = json.dumps(modified_response)
                        for old_value, new_value in difference_map.items():
                            response_text = response_text.replace(old_value, new_value)
                        return Response(response_text, mimetype="application/json")
                    else:
                        response_text = modified_response
                        for old_value, new_value in difference_map.items():
                            response_text = response_text.replace(old_value, new_value)
                        return Response(response_text, mimetype=mock["mime_type"])

            return jsonify({"error": "No matching response found"}), 404

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    print(f"Starting server on port {port}...")
    app.run(port=port, debug=False, use_reloader=False)

# Start servers in separate threads
for port, responses in mock_responses.items():
    threading.Thread(target=create_mock_server, args=(port, responses), daemon=True).start()

# Display domain-to-port mapping
print("\nDomain-to-Port Mapping:")
for domain, port in domain_ports.items():
    print(f"{domain} -> localhost:{port}")

# Keep the main thread alive
try:
    while True:
        pass
except KeyboardInterrupt:
    print("\nShutting down...")
