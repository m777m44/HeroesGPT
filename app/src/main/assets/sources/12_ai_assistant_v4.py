import requests
import json
import sys
import urllib3
import logging

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DeepSeekChat:
    
    AVAILABLE_MODELS = {
        "1": {
            "id": "deepseek/deepseek-r1",
            "name": "DeepSeek R1"
        },
        "2": {
            "id": "deepseek/deepseek-v3.2",
            "name": "DeepSeek V3.2"
        },
        "3": {
            "id": "deepseek/deepseek-v4-flash",
            "name": "DeepSeek V4 Flash"
        }
    }
    
    def __init__(self, model_id=None, debug=False):
        self.base_url = "https://deep-seek.ai/api/chat"
        self.session = requests.Session()
        self.conversation_history = []
        self.debug = debug
        
        if self.debug:
            logger.setLevel(logging.DEBUG)
        
        if model_id:
            self.model = model_id
        else:
            self.model = self.AVAILABLE_MODELS["1"]["id"]
        
        self.headers = {
            'Host': 'deep-seek.ai',
            'Connection': 'keep-alive',
            'sec-ch-ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
            'Origin': 'https://deep-seek.ai',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://deep-seek.ai/ar/chat',
            'Accept-Language': 'ar-AE,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
        }
        
        self.cookies = {
            'XSRF-TOKEN': 'eyJpdiI6Ikhzc0hiVlVPTWlMMkw1d0hselBwbGc9PSIsInZhbHVlIjoiMGJYSnhnUGNETWJnRVU5VUJpOE9TTjh6cWNqQjNWMmx6QXdHR2dZZiswaTdIK3hCVDFBY3hHV0Y2OXl4Uktxc1NPQmxiM2t4WGZuaXpTR1o4dnIzY0FYTUU5Y3FkN0xjSnA3OVdmd3BFaWN4RXdmZXVIREM1K2h0R0JUVnFxMFIiLCJtYWMiOiI0YTg5ZjMwOTQyYjM4NjM5MjZhZDE4OWJmYTE4YTE3MjdhMGQyYWM2N2JjMDY2MzAyNTZhZTIzNjZmMzYyOTgyIiwidGFnIjoiIn0=',
            'deepseek_session': 'eyJpdiI6Ild6YU5OQ1RqalJJNlplT2UxZ3hMT0E9PSIsInZhbHVlIjoiZVFtNTZsUXR6dExHdHYrcWRNVUxaY3BINFlZMHNubWhRWFM0eGE4VWdKd2lkRjI3WUsxVGV0em9qRFZYQUI5dkc1S3FHdzg2b0hHcENmRm52eVNLQTAxUUxTYnErVExKU1BoL3VDUThRVWgrbnVzZjdKQVNqam9RR1haaUtxRUciLCJtYWMiOiIyOWRjODFkYTkyMTYzNjNmMjgxOTkyYWMzNThmMzgyZTllYWVkY2NlYzIyYWEyMTU2YTk4ZjMyOTVhMzY5ZDY4IiwidGFnIjoiIn0=',
            '_ga': 'GA1.1.2144522985.1786432826',
            '_ga_C2YCJFV9N4': 'GS2.1.s1786432825$o1$g0$t1786432826$j59$l0$h0',
        }
        
        self.headers['X-CSRF-TOKEN'] = self.cookies['XSRF-TOKEN'].split('%3D')[0] + '='
    
    @classmethod
    def select_model(cls):
        print("Select Model:")
        for key, model in cls.AVAILABLE_MODELS.items():
            print(f"  {key}. {model['name']}")
        
        while True:
            choice = input("Choose (1-3): ").strip()
            if not choice:
                choice = "1"
            if choice in cls.AVAILABLE_MODELS:
                return cls.AVAILABLE_MODELS[choice]['id']
            print("Invalid choice")
    
    def send_message(self, message):
        self.conversation_history.append({
            "role": "user",
            "content": message
        })
        
        payload = {
            "model": self.model,
            "messages": self.conversation_history,
            "temperature": 0.7,
            "max_tokens": 2000,
            "stream": True
        }
        
        try:
            response = self.session.post(
                self.base_url,
                headers=self.headers,
                cookies=self.cookies,
                json=payload,
                verify=False,
                timeout=60,
                allow_redirects=True,
                stream=True
            )
            
            response.raise_for_status()
            
            full_content = ""
            
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                line = line.strip()
                
                if line.startswith(':'):
                    continue
                
                if line.startswith('data: '):
                    data_str = line[6:]
                    
                    if data_str == '[DONE]':
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        if 'choices' in data and len(data['choices']) > 0:
                            delta = data['choices'][0].get('delta', {})
                            
                            if 'content' in delta and delta['content']:
                                content_chunk = delta['content']
                                print(content_chunk, end='', flush=True)
                                full_content += content_chunk
                    
                    except json.JSONDecodeError:
                        if self.debug:
                            logger.debug(f"Failed to parse: {data_str[:50]}")
                        continue
            
            print()
            
            self.conversation_history.append({
                "role": "assistant",
                "content": full_content
            })
            
            return full_content
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None
    
    def test_connection(self):
        try:
            response = self.session.get(
                'https://deep-seek.ai/ar/chat',
                headers={'User-Agent': self.headers['User-Agent']},
                verify=False,
                timeout=10
            )
            return response.status_code == 200
        except:
            return False
    
    def switch_model(self):
        print("Select Model:")
        for key, model in self.AVAILABLE_MODELS.items():
            print(f"  {key}. {model['name']}")
        
        while True:
            choice = input("Choose (1-3): ").strip()
            if choice in self.AVAILABLE_MODELS:
                self.model = self.AVAILABLE_MODELS[choice]['id']
                print(f"Switched to {self.AVAILABLE_MODELS[choice]['name']}")
                break
            print("Invalid choice")
    
    def clear_history(self):
        self.conversation_history = []
        print("History cleared")


def interactive_chat():
    model_id = DeepSeekChat.select_model()
    chat = DeepSeekChat(model_id=model_id)
    
    
    
    
    while True:
        try:
            user_input = input("\nانت >> ").strip()
            
            if user_input.lower() == 'exit':
                break
            elif user_input.lower() == 'clear':
                chat.clear_history()
                continue
            elif user_input.lower() == 'model':
                chat.switch_model()
                continue
            elif not user_input:
                continue
            
            print("ai >>> ", end='', flush=True)
            chat.send_message(user_input)
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def single_message(message, model_id=None):
    if not model_id:
        model_id = DeepSeekChat.AVAILABLE_MODELS["1"]["id"]
    
    chat = DeepSeekChat(model_id=model_id)
    print("ai >>> ", end='', flush=True)
    chat.send_message(message)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='محادثة ديب سيك')
    parser.add_argument('-m', '--message', type=str, help='Send single message')
    parser.add_argument('--model', type=str, default=None, help='Model to use')
    parser.add_argument('--debug', action='store_true', help='Debug mode')
    parser.add_argument('--list-models', action='store_true', help='List available models')
    
    args = parser.parse_args()
    
    if args.list_models:
        for key, model in DeepSeekChat.AVAILABLE_MODELS.items():
            print(f"{key}. {model['name']}")
        return
    
    if args.message:
        single_message(args.message, model_id=args.model)
    else:
        interactive_chat()


if __name__ == "__main__":
    main()