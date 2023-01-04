from chatgpt_wrapper import ChatGPT
import json
from time import sleep, perf_counter
from datetime import datetime
from pathlib import Path
import os
import logging
import re
import uuid

timestamp = str(datetime.now()).replace(' ', '_').replace(':', '-')


def config_logger(timestamp):
    logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.INFO)

    fileHandler = logging.FileHandler("{0}.log".format(timestamp))
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)


def send_request(prompt_template, category_name, subcategory_name):
    prompt = prompt_template.format(cat=category_name, subcat=subcategory_name)
    start_time = perf_counter()
    response = bot.ask(prompt)
    response_time = perf_counter() - start_time
    return response, response_time


def save_response(response, save_dir, filename):
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    save_path = os.path.join(save_dir, f'{filename}.json')
    with open(save_path, 'w') as save_file:
        save_file.write(response)


def parse_response(response):
    response = response[response.find('{'):response.rfind('}')+1]

    json_content = json.loads(response)
    question_str = json_content['question']['en']
    # remove bad characters
    question_str = re.sub(r'[^\s\w_. -]', '_', question_str)
    return json.dumps(json_content), question_str


config_logger(timestamp)
bot = ChatGPT()
with open('prompts.txt', 'r') as prompt_template_file:
    prompt_template = prompt_template_file.read()
requests = 0
n_request_attempts = 3

with open('topics.json', 'r') as topics_file:
    topics = json.load(topics_file)
    for category in topics['categories']:
        category_name = category['name']
        for subcategory_name in category['subcategories']:
            for i in range(n_request_attempts):
                requests += 1
                try:
                    logging.info(f"send request #{requests}...")
                    response, response_time = send_request(prompt_template, category_name, subcategory_name)
                except Exception as ex:
                    logging.exception(f'request {requests} failed')
                    sleep(120)
                    continue
                else:
                    logging.info(f"request #{requests} ok in {response_time}")

                save_dir = os.path.join('results', category_name, subcategory_name)
                save_dir_fails = os.path.join(save_dir, 'failed')
                try:
                    parsed_response, question_str = parse_response(response)
                except Exception as ex:
                    logging.exception(f'parsing response #{requests} with {response} failed')
                    save_response(response, save_dir_fails, str(uuid.uuid4()))
                    continue
                else:
                    logging.info(f"parsing response #{requests} ok")

                try:
                    save_response(parsed_response, save_dir, question_str)
                except Exception as ex:
                    logging.exception(f'saving response #{requests} with {response} failed')
                    continue
                else:
                    logging.info(f"saving response #{requests} ok")
                    sleep(10)
                    break
