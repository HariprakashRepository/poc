import json
import re
import textwrap
from collections import defaultdict
from termcolor import colored
from tabulate import tabulate
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import csv
import os
from urllib.parse import urlparse
from haralyzer import HarParser

CONFIG_FILE = 'Config.json'
OUTPUT_FILE = 'Generated_K6script.js'
correlated_data  = []
# Function to wrap text
def wrap_text(text, width=90):
    return "\n".join(textwrap.wrap(text, width))

def capture_boundaries(text, key_value_pair):
    start_idx = text.find(key_value_pair)
    
    # If key-value pair is not found, return default values
    if start_idx == -1:
        return "NoLeftBoundary", "NoRightBoundary"
    
    end_idx = start_idx + len(key_value_pair)
    
    # Define left boundary (10 characters before key-value)
    left_boundary = text[max(0, start_idx-10):start_idx].strip() or "NoLeftBoundary"

    # Define right boundary (10 characters after key-value)
    right_boundary = text[end_idx:end_idx+10].strip() or "NoRightBoundary"

    # If right boundary is still empty, find the boundary based on the next space
    if right_boundary == "NoRightBoundary":
        remainder_text = text[end_idx:]
        space_idx = remainder_text.find(' ')
        
        if space_idx != -1:
            right_boundary = remainder_text[:space_idx].strip() or "NoRightBoundary"
        else:
            right_boundary = remainder_text.strip() or "NoRightBoundary"

    # Validate the captured key-value pair (re-extract and compare)
    extracted_value = f"{text[start_idx:end_idx]}"
    
    if extracted_value != key_value_pair:
        return left_boundary, "NoRightBoundary"  # If the extracted value doesn't match, return default for the right boundary

    return left_boundary, right_boundary

# Function to check if a request is a GraphQL call
def is_graphql_request(entry):
    url = entry['request']['url']
    if 'graphql' in url.lower():
        return True
    if 'postData' in entry['request']:
        post_data = entry['request']['postData'].get('text', '')
        try:
            post_data_json = json.loads(post_data)
            if 'query' in post_data_json:
                return True
        except (json.JSONDecodeError, TypeError):
            pass
    return False

# A thread lock to ensure thread-safe updates to the shared occurrence dictionary
occurrence_lock = threading.Lock()

def analyze_transaction(entry, idx, include_response_body):
    transaction_seen_keys = set()
    results = []

    def find_key_value_pairs(data, section_name):
        key_value_pattern = re.compile(r'(\b\w+\b)=([\w@:%\.\+\-\_]+)')
        matches = key_value_pattern.findall(data)
        
        for match in matches:
            key, value = match

            if len(key) > 5 or len(value) > 1:
                key_value_str = f"{key}={value}"
                if key_value_str in transaction_seen_keys:
                    continue
                transaction_seen_keys.add(key_value_str)

                left_boundary, right_boundary = capture_boundaries(data, key_value_str)
                result = {
                    'key_value': key_value_str,
                    'section': section_name,
                    'transaction': idx + 1,
                    'boundary': (left_boundary, right_boundary)
                }
                results.append(result)
    
    # Check URL
    url = entry['request']['url']
    find_key_value_pairs(url, 'URL')

    # Check request headers
    for header in entry['request']['headers']:
        find_key_value_pairs(header['value'], 'Request Header')

    # Check request body (if present)
    if 'postData' in entry['request']:
        request_body = entry['request']['postData'].get('text', '')
        find_key_value_pairs(request_body, 'Request Body')

    # Check response headers
    for header in entry['response']['headers']:
        find_key_value_pairs(header['value'], 'Response Header')

    # Check response body if required
    if include_response_body and 'text' in entry['response']['content']:
        response_body = entry['response']['content'].get('text', '')
        find_key_value_pairs(response_body, 'Response Body')
    
    return results

# def analyze_har_for_occurrences_with_boundaries_concurrent(har_file_path, include_response_body=False):
#     with open(har_file_path, 'r', encoding='utf-8') as f:
#         har_data = json.load(f)

#     total_transactions = len(har_data['log']['entries'])

#     # Dictionary to store occurrences
#     occurrence_dict = defaultdict(lambda: {
#         'count': 0,
#         'locations': [],
#         'first_occurrence': {'section': None, 'transaction': None, 'boundary': None, 'response_code': None}
#     })

#     # Use a ThreadPoolExecutor for concurrent processing
#     with ThreadPoolExecutor() as executor:
#         futures = []
#         for idx, entry in enumerate(har_data['log']['entries']):
#             # Submit each transaction processing task to the thread pool
#             futures.append(executor.submit(analyze_transaction, entry, idx, include_response_body))

#         # Process each result as it completes
#         for future in as_completed(futures):
#             transaction_results = future.result()
#             with occurrence_lock:
#                 for result in transaction_results:
#                     key_value_str = result['key_value']
#                     occurrence_info = occurrence_dict[key_value_str]
#                     occurrence_info['count'] += 1
#                     occurrence_info['locations'].append({
#                         'section': result['section'],
#                         'transaction': result['transaction']
#                     })
                    
#                     if occurrence_info['first_occurrence']['section'] is None:
#                         response_code = har_data['log']['entries'][result['transaction'] - 1]['response']['status']
#                         if response_code != 200:
#                             occurrence_info['first_occurrence'] = {
#                                 'section': result['section'],
#                                 'transaction': result['transaction'],
#                                 'boundary': result['boundary'],
#                                 'response_code': response_code
#                             }

#     # Prepare table for output
#     table_data = []
#     global correlated_data 
#     for idx, (key_value, details) in enumerate(occurrence_dict.items(), start=1):
#         if details['count'] > 1:
#             if details['count'] == total_transactions:
#                 continue

#             first_occurrence = details['first_occurrence']
#             if not first_occurrence or first_occurrence['boundary'] is None or first_occurrence['response_code'] == 200:
#                 continue

#             transactions_str = ", ".join(map(str, [loc['transaction'] for loc in details['locations']]))
#             wrapped_key_value = wrap_text(colored(key_value, 'green'), 50)
#             wrapped_first_occurrence_section = wrap_text(colored(first_occurrence['section'], 'yellow'), 50)
#             wrapped_first_occurrence_transaction = wrap_text(colored(str(first_occurrence['transaction']), 'cyan'), 50)
#             wrapped_transactions = wrap_text(colored(transactions_str, 'cyan'), 50)

#             # Use the boundary information from the capture_boundaries function
#             left_boundary, right_boundary = first_occurrence['boundary']
#             boundary_str = f"Left: {left_boundary}, Right: {right_boundary}"

#             table_data.append([
#                 idx,
#                 wrapped_first_occurrence_transaction,
#                 wrapped_first_occurrence_section,
#                 details['count'],
#                 wrapped_key_value,
#                 wrapped_transactions,
#                 boundary_str
#             ])
#             donothing=0
#             # Create correlated data
#             for location in details['locations']:
#                 if details['count'] > 1:
#                     if details['count'] == total_transactions:
#                        continue
#                     first_occurrence = details['first_occurrence']
#                     if not first_occurrence or first_occurrence['boundary'] is None or first_occurrence['response_code'] == 200:
#                         continue
#                     transaction_number = location['transaction']
#                     section = location['section']
#                     left_boundary = str(first_occurrence['boundary'][0]).replace("(","\\(")
#                     right_boundary = str(first_occurrence['boundary'][1]).replace("(","\\(")

#                     if section == 'Response Header' and left_boundary != 'NoLeftBoundary' and right_boundary !='NoRightBoundary':
#                         correlated_data.append(f"Transaction_{transaction_number},response.headers,{left_boundary}delimiter{right_boundary}")
#                     elif section == 'Request Header' and left_boundary != 'NoLeftBoundary' and right_boundary !='NoRightBoundary':
#                         correlated_data.append(f"Transaction_{transaction_number},response.request.headers,{left_boundary}delimiter{right_boundary}")
#                     elif section == 'URL' and left_boundary != 'NoLeftBoundary' and right_boundary !='NoRightBoundary':
#                         correlated_data.append(f"Transaction_{transaction_number},response.url,{left_boundary}delimiter{right_boundary}")
#                     else:
#                         donothing=donothing+1
#                 # correlated_data.append(f"Transaction_{transaction_number},request.url,{left_boundary}delimiter{right_boundary}")

#     # Print the table if data is available
#     if table_data:
#         headers = [
#             colored("No", 'red'),
#             colored("First Occurrence Transaction", 'red'),
#             colored("First Occurrence Section", 'red'),
#             colored("Total Occurrences", 'red'),
#             colored("Key-Value Pair", 'red'),
#             colored("Transactions", 'red'),
#             colored("Boundaries", 'red')
#         ]
#         # print(tabulate(table_data, headers, tablefmt="grid"))
#         print("Total correlations possible: " + str(len(table_data)))
#     else:
#         print(colored("No key-value pairs with more than 1 occurrence found.", 'red'))
#     correlated_data=sorted(correlated_data)
#     # Print correlated data
#     if correlated_data:
#         print("\nCorrelated Data:")
#         for data in correlated_data:
#             print(data)
#         print("donothing :"+str(donothing))
#     else:
#         print(colored("No correlated data found.", 'red'))
#     return correlated_data
# # Example usage
def analyze_har_for_occurrences_with_boundaries_concurrent(har_file_path, include_response_body=False, mime_types=None):
    with open(har_file_path, 'r', encoding='utf-8') as f:
        har_data = json.load(f)

    total_transactions = len(har_data['log']['entries'])

    # Dictionary to store occurrences
    occurrence_dict = defaultdict(lambda: {
        'count': 0,
        'locations': [],
        'first_occurrence': {'section': None, 'transaction': None, 'boundary': None, 'response_code': None}
    })

    # Use a ThreadPoolExecutor for concurrent processing
    with ThreadPoolExecutor() as executor:
        futures = []
        for idx, entry in enumerate(har_data['log']['entries']):
            # Check if MIME type is in the given list
            mime_type = entry['response'].get('content', {}).get('mimeType', '')
            if mime_types and mime_type not in mime_types:
                continue  # Skip this entry if MIME type is not in the list

            # Submit each transaction processing task to the thread pool
            futures.append(executor.submit(analyze_transaction, entry, idx, include_response_body))

        # Process each result as it completes
        for future in as_completed(futures):
            transaction_results = future.result()
            with occurrence_lock:
                for result in transaction_results:
                    key_value_str = result['key_value']
                    occurrence_info = occurrence_dict[key_value_str]
                    occurrence_info['count'] += 1
                    occurrence_info['locations'].append({
                        'section': result['section'],
                        'transaction': result['transaction']
                    })
                    
                    if occurrence_info['first_occurrence']['section'] is None:
                        response_code = har_data['log']['entries'][result['transaction'] - 1]['response']['status']
                        if response_code != 200:
                            occurrence_info['first_occurrence'] = {
                                'section': result['section'],
                                'transaction': result['transaction'],
                                'boundary': result['boundary'],
                                'response_code': response_code
                            }

    # Prepare table for output
    table_data = []
    global correlated_data 
    for idx, (key_value, details) in enumerate(occurrence_dict.items(), start=1):
        if details['count'] > 1:
            if details['count'] == total_transactions:
                continue

            first_occurrence = details['first_occurrence']
            if not first_occurrence or first_occurrence['boundary'] is None or first_occurrence['response_code'] == 200:
                continue

            transactions_str = ", ".join(map(str, [loc['transaction'] for loc in details['locations']]))

            wrapped_key_value = wrap_text(colored(key_value, 'green'), 50)
            wrapped_first_occurrence_section = wrap_text(colored(first_occurrence['section'], 'yellow'), 50)
            wrapped_first_occurrence_transaction = wrap_text(colored(str(first_occurrence['transaction']), 'cyan'), 50)
            wrapped_transactions = wrap_text(colored(transactions_str, 'cyan'), 50)

            # Use the boundary information from the capture_boundaries function
            left_boundary, right_boundary = first_occurrence['boundary']
            boundary_str = f"Left: {left_boundary}, Right: {right_boundary}"

            table_data.append([
                idx,
                wrapped_first_occurrence_transaction,
                wrapped_first_occurrence_section,
                details['count'],
                wrapped_key_value,
                wrapped_transactions,
                boundary_str
            ])

            # Create correlated data
            for location in details['locations']:
                if details['count'] > 1:
                    if details['count'] == total_transactions:
                        continue
                    first_occurrence = details['first_occurrence']
                    if not first_occurrence or first_occurrence['boundary'] is None or first_occurrence['response_code'] == 200:
                        continue
                    transaction_number = location['transaction']
                    section = location['section']
                    left_boundary = str(first_occurrence['boundary'][0]).replace("(","\\(")
                    right_boundary = str(first_occurrence['boundary'][1]).replace("(","\\(")

                    if section == 'Response Header' and left_boundary != 'NoLeftBoundary' and right_boundary !='NoRightBoundary':
                        correlated_data.append(f"Transaction_{transaction_number},response.headers,{left_boundary}delimiter{right_boundary}")
                    elif section == 'Request Header' and left_boundary != 'NoLeftBoundary' and right_boundary !='NoRightBoundary':
                        correlated_data.append(f"Transaction_{transaction_number},response.request.headers,{left_boundary}delimiter{right_boundary}")
                    elif section == 'URL' and left_boundary != 'NoLeftBoundary' and right_boundary !='NoRightBoundary':
                        correlated_data.append(f"Transaction_{transaction_number},response.url,{left_boundary}delimiter{right_boundary}")

    # Print the table if data is available
    if table_data:
        headers = [
            colored("No", 'red'),
            colored("First Occurrence Transaction", 'red'),
            colored("First Occurrence Section", 'red'),
            colored("Total Occurrences", 'red'),
            colored("Key-Value Pair", 'red'),
            colored("Transactions", 'red'),
            colored("Boundaries", 'red')
        ]
        print("Total correlations possible: " + str(len(table_data)))
    else:
        print(colored("No key-value pairs with more than 1 occurrence found.", 'red'))
    
    correlated_data = sorted(correlated_data)

    # Print correlated data
    if correlated_data:
        print("\nCorrelated Data:"+ str(len(correlated_data)))
        for data in correlated_data:
            print(data)
    else:
        print(colored("No correlated data found.", 'red'))
    return correlated_data
     


def get_rows_by_transaction(transaction_name):
    """
    Function to get all rows that match a given transaction name.
    """
    global correlated_data 
    # Filter the correlated_data array for rows containing the specified transaction name
    filtered_rows = [row for row in correlated_data if transaction_name in row]
    
    return filtered_rows

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

        
        # print("transaction_name:"+str(transaction_name))
        # print("convert :"+str(len(correlated_data)))
        filtered_rows = get_rows_by_transaction(transaction_name)
        # print("filtered_rows :"+str(len(filtered_rows)))
        if int(len(filtered_rows)) > 1:
            script += f"    correlate: [\n"
            for l in range(0,int(len(filtered_rows)-1)):
                location_to_extract=filtered_rows[l]
                tr=str(location_to_extract).replace(",request","^^^request").replace(",response","^^^response").replace(".headers,",".headers^^^").replace(".url,",".url^^^").replace(".body,",".body^^^").replace("delimiter","^^^").replace("/","\\/")
                fr=str(tr).split("^^^")
                trname=transaction_name.replace("Transaction_","T")
                script += f"      {{ variable: 'C_{trname}_value_{l}', extractor: (response) => {{let x = extractAll({fr[1]},/{fr[2]}(.*?){fr[3]}/g); return x[0] }}, exitOnFail: true }},\n"
                
            script += f"    ],\n"
            script += '  },\n\n'
        else:
            script += '  },\n\n'
        # script += '  },\n\n'
    # script += '  },\n\n'    
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
 

if __name__ == "__main__":

    print("Please Choose Anyone of the options")
    print("  1.Convert Whole har file to mk6.")
    print("  2.Remove Domains which is not required with domain or .extension .")
    print("Note:-")
    print("   *unwanted calls example : .ai,google,cloudflare,sdk,.net,.js,.css,.co.in,paypal,.svg,.ico,.woff,.png,.jpg,.ttf")
    input_choose_option = input("Enter Option: ")
    if int(input_choose_option) == 1:
        input_string = input("Enter har file names separated by commas: ")
        file_names = input_string.split(',')
        file_names = [file_name.strip() for file_name in file_names]
        output_file_path = "combined.har"
        combined_har_data = combine_har_files(file_names)
        save_combined_har(combined_har_data, output_file_path)
        payload_folderName=create_folder("Request_body_template")
        mime_types = ['application/json', 'text/html','text/plain','application/x-www-form-urlencoded','text/plain;charset=UTF-8','other']
        print(mime_types)
        next_1=input("would you like to modify (yes/no):")
        if next_1=="yes":
            next_2=input("give them comma seperated (i.e) application/json,text/html:")
            mime_types=str(next_2).split(",")
            analyze_har_for_occurrences_with_boundaries_concurrent(output_file_path, include_response_body=True,mime_types=mime_types)
        elif next_1=="no":
            analyze_har_for_occurrences_with_boundaries_concurrent(output_file_path, include_response_body=True,mime_types=mime_types)
        else:
            print("invalid input try again!")
        main("combined.har")
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
            remove_domains_from_har(output_file_path, DomainNameToRemove, "combined.har")
            mime_types = ['application/json', 'text/html','text/plain','application/x-www-form-urlencoded','text/plain;charset=UTF-8','other']
            print(mime_types)
            next_1=input("would you like to modify (yes/no):")
            if next_1=="yes":
               next_2=input("give them comma seperated (i.e) application/json,text/html:")
               mime_types=str(next_2).split(",")
               analyze_har_for_occurrences_with_boundaries_concurrent(output_file_path, include_response_body=True,mime_types=mime_types)
            elif next_1=="no":
               analyze_har_for_occurrences_with_boundaries_concurrent(output_file_path, include_response_body=True,mime_types=mime_types)
            else:
               print("invalid input try again!")
            main("combined.har")
        else:
            print("Invalid Input !")   
    else:
        print("Invalid Input !")



# filtered_rows = get_rows_by_transaction(transaction_name,c_correlated_data)


# analyze_har_for_occurrences_with_boundaries_concurrent("try2.har", include_response_body=True)