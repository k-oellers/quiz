from __future__ import print_function

from chatgpt_wrapper import ChatGPT
import json
from time import sleep, perf_counter
from datetime import datetime
from pathlib import Path
import os
import sys
import logging
import re
import uuid
from typing import Tuple, Union, Dict, Any, List
import threading
import argparse
try:
    import thread
except ImportError:
    import _thread as thread

UNAVAILABLE_MESSAGE = "Unusable response produced by ChatGPT, maybe its unavailable."
TIMEOUT_IN_SECONDS = 120


def quit_function(fn) -> None:
    sys.stderr.flush()  # Python 3 stderr is likely buffered.
    thread.interrupt_main()  # raises KeyboardInterrupt


def exit_after(s):
    """
    use as decorator to exit process if
    function takes longer than s seconds
    """

    def outer(fn):
        def inner(*args, **kwargs):
            timer = threading.Timer(s, quit_function, args=[fn.__name__])
            timer.start()
            try:
                result = fn(*args, **kwargs)
            finally:
                timer.cancel()
            return result

        return inner

    return outer


def config_logger(logfile_name: str) -> None:
    log_formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(f"logs/{logfile_name}.log")
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)


@exit_after(TIMEOUT_IN_SECONDS)
def send_request(message: str, bot: ChatGPT) -> Tuple[str, float]:
    start_time = perf_counter()
    response = bot.ask(message)
    response_time = perf_counter() - start_time
    return response, response_time


def save_data(data: str, save_dir: str, filename: str) -> None:
    # ensure that save directory exists
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    save_path = os.path.join(save_dir, f'{filename}.json')
    with open(save_path, 'w') as save_file:
        save_file.write(data)


def remove_bad_characters(input: str) -> str:
    return re.sub(r'[^\s\w_. -]', '', input.replace(' ', '_'))


def json_parse_response(response: str):
    # only parse JSON part of response
    response = response[response.find('{'):response.rfind('}') + 1]
    json_content = json.loads(response)
    question_str = remove_bad_characters(json_content['question']['en'])
    return json.dumps(json_content), question_str


def parse_response(response: str, n_questions: int):
    questions = []
    for line in response.split('\n'):
        line = line.strip()
        if not line or not line[0].isdigit():
            continue

        first_letter = re.search(r'[A-Za-z]', line)
        if not first_letter:
            continue

        questions.append(line[first_letter.start():])

    if len(questions) < n_questions:
        raise Exception('invalid format')

    response = json.dumps(questions)
    return response, remove_bad_characters(response[:40])


def read_file_content(filename: str, parse_json: bool = False) -> Union[str, Dict[str, Any]]:
    with open(filename, 'r') as file:
        return json.load(file) if parse_json else file.read()


def read_adjectives(adjective_str: str) -> List[str]:
    return [line for line in adjective_str.split('\n')]


def start(opt: argparse.Namespace):
    timestamp = str(datetime.now()).replace(' ', '_').replace(':', '-')
    config_logger(timestamp)
    # init chatGPT bot
    bot = ChatGPT()
    adjectives = read_adjectives(read_file_content('adjective.txt'))
    # load prompt template from file
    prompt_template = read_file_content(opt.prompt_file)
    continue_template = read_file_content(opt.continue_file)
    topics = read_file_content(opt.topics_file, True)
    requests = 0

    for category in topics['categories']:
        category_name = category['name']
        # if category_name == 'Geography' or category_name == 'History':
        #     continue
        for sub_category_name in category['subcategories']:
            use_base_prompt = True
            bot.new_conversation()
            for call in range(opt.calls):
                for _ in range(opt.attempts):
                    requests += 1
                    try:
                        prompt = (prompt_template if use_base_prompt else continue_template).format(
                            calls=opt.calls,
                            category=category_name,
                            sub_category=sub_category_name,
                            questions=opt.questions,
                            ranks=opt.ranks,
                            prompt=', '.join(adjectives),
                        )
                        logging.info(f"send request #{requests}: {prompt}")
                        response, response_time = send_request(prompt, bot)
                    except Exception:
                        logging.exception(f'request {requests} failed')
                        sleep(opt.wait_error)
                        continue
                    except KeyboardInterrupt:
                        logging.error(f'request {requests} failed: Timeout reached')
                        sleep(opt.wait_error)
                        use_base_prompt = True
                        bot.new_conversation()
                        break

                    if response == UNAVAILABLE_MESSAGE:
                        logging.error(f'request {requests} failed: Service unavailable')
                        sleep(opt.wait_block)
                        continue

                    logging.info(f"request #{requests} ok in {response_time}s")
                    save_dir = os.path.join('results_v2', category_name, sub_category_name)
                    save_dir_fails = os.path.join(save_dir, 'failed')
                    try:
                        parsed_response, filename = parse_response(response, opt.questions)
                    except Exception:
                        logging.exception(f'parsing response #{requests} with {response} failed')
                        save_data(response, save_dir_fails, str(uuid.uuid4()))
                        use_base_prompt = True
                        bot.new_conversation()
                        break

                    logging.info(f"parsing response #{requests} ok")
                    try:
                        save_data(parsed_response, save_dir, filename)
                    except Exception:
                        logging.exception(f'saving response #{requests} with {response} failed')
                        continue

                    use_base_prompt = False
                    logging.info(f"saving response #{requests} ok")
                    sleep(opt.wait_success)
                    break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt_file", type=str, help="file for the first prompt")
    parser.add_argument("--continue_file", type=str, help="file for the following prompt")
    parser.add_argument("--topics_file", type=str, help="file for the following prompt")
    parser.add_argument("--timeout", default=120, type=int, help="timeout in seconds")
    parser.add_argument("--ranks", default=6, type=int, help="")
    parser.add_argument("--calls", default=3, type=int, help="")
    parser.add_argument("--questions", default=10, type=int, help="")
    parser.add_argument("--wait_success", default=5, type=int, help="")
    parser.add_argument("--wait_error", default=120, type=int, help="")
    parser.add_argument("--wait_block", default=600, type=int, help="")
    parser.add_argument("--attempts", default=5, type=int, help="")
    args = parser.parse_args()
    start(args)
