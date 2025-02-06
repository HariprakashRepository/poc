import json
import os
from urllib.parse import urlparse
from haralyzer import HarParser
import threading
import sys
import subprocess
import pip
from flask import Flask, request, jsonify, Response
import win32crypt
import win32con
import ctypes




CONFIG_FILE = 'Config.json'
OUTPUT_FILE = 'Generated_K6script.js'

def create_folder(folder_name):
    try:
        os.makedirs(folder_name)
        print(f"Folder '{folder_name}' created successfully.")
    except FileExistsError:
        print(f"Folder '{folder_name}' already exists.")
    except Exception as e:
        print(f"Error creating folder '{folder_name}': {e}")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as config_file:
            return json.load(config_file)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as config_file:
        json.dump(config, config_file, indent=2)

def extract_info(entry):
    request = entry.get('request', {})
    response = entry.get('response', {})
   
    url = request.get('url', '')
    method = request.get('method', '')
    body = request.get('postData', {}).get('text', '')
    headers = request.get('headers', [])

    return {'url': url, 'method': method, 'body': body, 'headers': headers}

def parse_harold(har_filename):
    with open(har_filename, 'r', encoding='utf-8') as har_file:
        har_data = json.load(har_file)

    entries = har_data.get('log', {}).get('entries', [])

    extracted_data = []
    for entry in entries:
        info = extract_info(entry)
        extracted_data.append(info)

    return extracted_data

def parse_har(har_filename):
    try:
        with open(har_filename, 'r', encoding='utf-8') as har_file:
            har_data = json.load(har_file)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return []

    entries = har_data.get('log', {}).get('entries', [])

    extracted_data = []
    for entry in entries:
        info = extract_info(entry)
        extracted_data.append(info)

    return extracted_data

def write_body_to_file(transaction_name, body,payload_folderName):
    filename = os.getcwd()+"\\"+payload_folderName+"\\"+f"{transaction_name}.txt"
    filename_return="./"+payload_folderName+"/"+f"{transaction_name}.txt"
    with open(filename, 'w', encoding='utf-8') as body_file:
        body_file.write(body)
    return filename_return

def replace_common_domains(url, domain_mapping):
    for common_domain, placeholder in domain_mapping.items():
        url = url.replace(common_domain, f'${{{placeholder}}}')
    return url

def replace_specific_urls(url, specific_url_mapping):
    for specific_url, placeholder in specific_url_mapping.items():
        url = url.replace(specific_url, f'${{{placeholder}}}')
    return url

def convert_to_k6_script(extracted_data):
    script = 'import { sleep } from \'k6\';\n\n'
   
    domain_mapping = load_config()
    specific_url_mapping = {}
    current_placeholder_index = len(domain_mapping) + 1

    method_counts = {}

    for i, entry in enumerate(extracted_data, 1):
        method = entry['method']
        method_counts[method] = method_counts.get(method, 0) + 1

        script += f'export let headers_{i:02} = {{\n'
        for header in entry['headers']:
            # if header['name'] =="Cookie":
            #    print(f"caps Cookie Ignored -headers_{i:02}")
            # elif header['name']=="cookie":
            #    print(f"small cookie Ignored -headers_{i:02}")  
            # else:
            script += f"  '{header['name']}': '{header['value']}',\n"
               
        script += '}\n\n'

    script += 'export let PageDef = {\n\n'

    for i, entry in enumerate(extracted_data, 1):
        transaction_name = f'Transaction_{i}'

        url_with_placeholder = replace_common_domains(entry['url'], domain_mapping)

        url_with_placeholder = replace_specific_urls(url_with_placeholder, specific_url_mapping)

        script += f"  {transaction_name}: {{\n"
        script += f"    service: '{url_with_placeholder}',\n"
        script += f"    headers: headers_{i:02},\n"
        script += f"    method: '{entry['method']}',\n"

        if entry['body']:
           
            body_filename = write_body_to_file(transaction_name, entry['body'],"Request_body_template")
            script += f"    request_body_template: '{body_filename}',\n"

        script += f"    checks: [\n"
        script += f"      {{ message: 'check {transaction_name}', validate: (response) => response.status === '200', exitOnFail: true }},\n"
        script += f"    ],\n"

        script += '  },\n\n'

    script += '}\n\n'

    script += 'export let opencart_flowdef = {\n'
    script += '  flowname: {\n'
    script += '    thinktime: 3,\n'
    script += '    sessionpacing: 2,\n'
    script += '    percent: 100,\n'
    script += '    flow: [\n'

    for i, entry in enumerate(extracted_data, 1):
        script += f"      {{ Transaction_{i}: {{ page: PageDef.Transaction_{i} }} }},\n"

    script += '    ]\n'
    script += '  }\n'
    script += '}\n'

    script += '\n// Method Counts:\n'
    for method, count in method_counts.items():
        script += f'// {method}: {count}\n'

    save_config(domain_mapping)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as output_file:
        output_file.write(script)

    # har_filename = 'opencart.har'
    # extracted_data = parse_har(har_filename)

def main(harfilename):
    har_filename = str(harfilename)
    extracted_data = parse_har(har_filename)

    unique_domains = set()
    for entry in extracted_data:
        url = entry['url']
        domain = urlparse(url).netloc
        unique_domains.add(domain)

   
    domain_mapping = {f'BASE_URL_{i + 1}': domain for i, domain in enumerate(unique_domains)}

    save_config(domain_mapping)

    convert_to_k6_script(extracted_data)

def combine_har_files(file_paths):
    combined_entries = []

    for file_path in file_paths:
        with open(file_path, 'r', encoding='utf-8') as har_file:
            har_data = json.load(har_file)
            har_parser = HarParser(har_data)

            # Check for different HAR structures
            if 'log' in har_parser.har_data:
                entries = har_parser.har_data['log']['entries']
            elif 'entries' in har_parser.har_data:
                entries = har_parser.har_data['entries']
            else:
                print(f"Invalid HAR structure in {file_path}")
                continue

            combined_entries.extend(entries)

    combined_har = {"log": {"version": "1.2", "entries": combined_entries}}
    return combined_har

def save_combined_har(combined_har, output_file_path):
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        json.dump(combined_har, output_file, ensure_ascii=False, indent=2)

def remove_domains_from_har(har_file_path, domains_to_remove, output_file_path):
    with open(har_file_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)
 
    filtered_entries = []
    for entry in har_data['log']['entries']:
        url = entry['request']['url']
        if not any(domain in url for domain in domains_to_remove):
            filtered_entries.append(entry)
 
    har_data['log']['entries'] = filtered_entries
 
    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(har_data, f, ensure_ascii=False, indent=4)
 
    print(f"Domains {domains_to_remove} removed from HAR file. Updated file saved as '{output_file_path}'.")

def remove_entries_with_words_from_har(har_file_path, words_to_remove, output_file_path):
    words_list = [word.strip() for word in str(words_to_remove).split(",")]
 
    with open(har_file_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)
 
    filtered_entries = [
        entry for entry in har_data['log']['entries']
        if not any(word in entry['request']['url'] for word in words_list)
    ]
 
    har_data['log']['entries'] = filtered_entries
 
    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(har_data, f, ensure_ascii=False, indent=4)
 
    print(f"Entries with URLs containing any of {words_list} removed from HAR file. Updated file saved as '{output_file_path}'.")

def install_package(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])
def check_and_install(module):
    try:
        __import__(module)
    except ImportError:
        print(f"Module {module} not found. Installing...")
        install_package(module)

def generate_certificate(cert_dir="certs"):
    if not os.path.exists(cert_dir):
        os.makedirs(cert_dir)
    cert_key_path = os.path.join(cert_dir, "server.key")
    cert_csr_path = os.path.join(cert_dir, "server.csr")
    cert_crt_path = os.path.join(cert_dir, "server.crt")
    if not os.path.exists(cert_key_path) or not os.path.exists(cert_crt_path):
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-out", cert_key_path])
        subprocess.run([
            "openssl", "req", "-new", "-key", cert_key_path, "-out", cert_csr_path,
            "-subj", "/C=IN/ST=TN/L=CHENNAI/O=HARI/OU=HARI/CN=HARI/emailAddress=HARI@INFO.COM"
        ])
        subprocess.run([
            "openssl", "x509", "-req", "-days", "365", "-in", cert_csr_path, "-signkey", cert_key_path, "-out", cert_crt_path
        ])
    
    print(f"Certificate and key have been generated and saved to {cert_dir}")
    return cert_key_path, cert_crt_path

def add_certificate_to_trusted_root(cert_path):
    try:
        store = win32crypt.CertOpenStore(win32con.CERT_STORE_PROV_SYSTEM, 0, None, win32con.CERT_SYSTEM_STORE_CURRENT_USER, "ROOT")
        
        with open(cert_path, "rb") as cert_file:
            cert_data = cert_file.read()
        
        cert_handle = win32crypt.CertCreateCertificateContext(win32con.X509_ASN_ENCODING, cert_data)
        if not cert_handle:
            print("Error: Failed to load certificate.")
            return False
        
        result = win32crypt.CertAddCertificateContextToStore(store, cert_handle, win32con.CERT_STORE_ADD_REPLACE_EXISTING, None)
        
        if result:
            print(f"Successfully added the certificate to Trusted Root Authorities: {cert_path}")
            return True
        else:
            print("Error: Failed to add the certificate.")
            return False
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return False

def create_mock_server(port, cert_key, cert_crt):
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
    @app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
    def mock_server(path):
        url_path = f"http://localhost:{port}/{path}" if path else f"http://localhost:{port}/"
        method = request.method

        print(f"Incoming request: {url_path} [{method}]")

        response = mock_data.get((url_path, method))

        if response:
            response_body = response["body"]
            response_type = response["type"]
            expected_headers = response["headers"]

            if headers_validation:
                request_headers = request.headers
                missing_headers = [header for header in expected_headers if header not in request_headers]

                if missing_headers:
                    print(f"Missing headers: {missing_headers}")
                    return jsonify({
                        "error": "Missing required headers",
                        "missing_headers": missing_headers
                    }), 400

            try:
                request_payload = request.get_json() or {}
            except:
                request_payload = {}

            if response_type == "json" and isinstance(response_body, dict) and isinstance(request_payload, dict):
                merged_response = {**response_body, **request_payload}
                return jsonify(merged_response), response["status"]

            return Response(response_body, status=response["status"], content_type=response_type)

        print(f"404 Not Found: {url_path} [{method}]")
        return jsonify({"error": "Mock response not found"}), 404


    if https_enabled:
        app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False, ssl_context=(cert_crt, cert_key))
    else:
        app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)




# python mockactualssl.py  --https=false --headers-validation=false
if __name__ == "__main__":

    print("Please Choose Anyone of the options")
    print("  1.Convert Whole har file to mk6.")
    print("  2.Remove Domains which is not required with domain or .extension .")
    print("  3.mock the whole har file")
    input_choose_option = input("Enter Option: ")
    if int(input_choose_option) == 1:
        input_string = input("Enter har file names separated by commas: ")
        file_names = input_string.split(',')
        file_names = [file_name.strip() for file_name in file_names]
        output_file_path = "combined.har"
        combined_har_data = combine_har_files(file_names)
        save_combined_har(combined_har_data, output_file_path)
        payload_folderName=create_folder("Request_body_template")
        main(output_file_path)
    elif int(input_choose_option) == 2:
        print("  1.Domain/Extension")
        input_choose_option2 = input("Enter Option: ") 
        if int(input_choose_option2) == 1:
            input_string_2 = input("Enter Domain/Extension names separated by commas: ")
            DomainNameToRemove=input_string_2.split(",")
            input_string = input("Enter har file names separated by commas: ")
            file_names = input_string.split(',')
            file_names = [file_name.strip() for file_name in file_names]
            output_file_path = "combined.har"
            combined_har_data = combine_har_files(file_names)
            save_combined_har(combined_har_data, output_file_path)
            payload_folderName=create_folder("Request_body_template")
            remove_domains_from_har(output_file_path, DomainNameToRemove, "Customized.har")
            main("Customized.har")
        else:
            print("Invalid Input !")
    elif int(input_choose_option)==3:
        required_modules = ["flask", "pywin32", "win32crypt"]
        # for module in required_modules:
            # check_and_install(module)
        try:
            input_choose_option5 = input("Enter harfile name: ")
            with open(str(input_choose_option5), "r", encoding="utf-8") as f:
                har_data = json.load(f)
        except Exception as e:
            print(f"Error loading HAR file: {e}")
            har_data = {"log": {"entries": []}}
        headers_validation = False 
        https_enabled = False
        for arg in sys.argv:
            if arg == "--headers-validation=false":
                headers_validation = False
            elif arg == "--https=false":
                https_enabled = False
            elif arg == "--https=true":
                https_enabled = True
        domains = set()
        mock_data = {}

        for entry in har_data["log"]["entries"]:
            request_data = entry.get("request", {})
            response_data = entry.get("response", {})

            url = request_data.get("url", "")
            method = request_data.get("method", "GET")

            parsed_url = urlparse(url)
            domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
            domains.add(domain)
        domain_port_mapping = {}
        base_port = 5000

        for domain in sorted(domains):
            domain_port_mapping[domain] = base_port
            base_port += 1
        print("\n🔹 Mocked Domains with Ports:")
        for domain, port in domain_port_mapping.items():
            print(f"  {domain} → localhost:{port}")        
        cert_key, cert_crt = None, None
        if https_enabled:
            cert_key, cert_crt = generate_certificate()
            add_certificate_to_trusted_root(cert_crt)
        else:
            print("HTTPS is disabled. Skipping certificate generation.")

        for entry in har_data["log"]["entries"]:
            request_data = entry.get("request", {})
            response_data = entry.get("response", {})

            url = request_data.get("url", "")
            method = request_data.get("method", "GET")

            parsed_url = urlparse(url)
            domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            local_url = url.replace(domain, f"http://localhost:{domain_port_mapping[domain]}")
            local_url = local_url.split("?")[0] 

            response_body_text = response_data.get("content", {}).get("text", "")

            try:
                response_body = json.loads(response_body_text) if response_body_text.strip().startswith("{") else response_body_text
                response_type = "json" if isinstance(response_body, dict) else "text/html"
            except json.JSONDecodeError:
                print(f"Warning: Invalid JSON response for {local_url}")
                response_body = response_body_text
                response_type = "text/html"

            mock_data[(local_url, method)] = {
                "status": response_data.get("status", 200),
                "body": response_body,
                "type": response_type,
                "headers": response_data.get("headers", {}),
            }
        for domain, port in domain_port_mapping.items():
            threading.Thread(target=create_mock_server, args=(port, cert_key, cert_crt), daemon=True).start()
            input("\n✅ Servers are running. Press Enter to stop...\n")   
    else:
        print("Invalid Input !")


