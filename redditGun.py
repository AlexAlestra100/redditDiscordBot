import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import time

load_dotenv()

config = {
    "TOKEN": os.getenv('TOKEN'),
    "CHANNEL_ID": int(os.getenv('CHANNEL_ID')),
    "USER_ID": os.getenv('USER_ID'),
    "URL": os.getenv('URL'),
    "KEYWORDS": os.getenv('KEYWORDS').split(','),
    "OTHER_KEYWORDS": os.getenv('OTHER_KEYWORDS').split(','),
    "USER_ID_2": os.getenv('USER_ID_2'),
    "URL_2": os.getenv('URL_2'),
}

CACHE = []
CACHE_EXPIRY = 15 * 60  # 15 minutes in seconds
CURR_PRICE = 0.0

def scrape_reddit():
    url = config['URL']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title_elements = soup.find_all('a', class_='block font-semibold text-neutral-content-strong m-0 visited:text-neutral-content-weak text-16 xs:text-18 mb-2xs xs:mb-xs')

    keywords = config['KEYWORDS']
    otherKeywords = config['OTHER_KEYWORDS']

    titles = []
    base_url = "https://www.reddit.com"
    for title_element in title_elements:
        if title_element.has_attr('slot') and title_element['slot'] == 'title':
            title = title_element.text
            if any(keyword.lower() in title.lower() for keyword in keywords):
                if any(otherKeyword.lower() in title.lower() for otherKeyword in otherKeywords):
                    href = title_element.get('href')
                    if not href.startswith(base_url):
                        href = base_url + href
                    titles.append({'title': title, 'link': href})
    return titles

def is_post_alerted(post):
    current_time = time.time()

    # Filter out expired posts
    global CACHE
    CACHE = [(timestamp, cached_post) for timestamp, cached_post in CACHE if current_time - timestamp < CACHE_EXPIRY]
    
    # Check if the post is in the filtered CACHE
    for timestamp, cached_post in CACHE:
        if cached_post['link'] == post['link']:
            return True
    return False

def add_post_to_cache(post):
    CACHE.append((time.time(), post))

# Custom scraper for the fish store
def scrape_fish():
    url = config['URL_2']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find the price
    price_span = soup.find('span', class_='price-item price-item--regular')

    if price_span:
        price_text = price_span.text.strip()
        if price_text:
            global CURR_PRICE
            price = float(price_text[1:])
            if CURR_PRICE != price:
                CURR_PRICE = price
                return True

    return False

class MyClient(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.msg_sent = False

    async def on_ready(self):
        channel = bot.get_channel(config['CHANNEL_ID'])
        await self.watcher1.start(channel)
        await self.watcher2.start(channel)

    @tasks.loop(seconds=20)
    async def watcher1(self, channel):
        posts = scrape_reddit()
        if posts:
            for post_data in posts:
                if not is_post_alerted(post_data):
                    user_id = config['USER_ID']
                    message = f"{user_id} \nTitle: {post_data['title']} \nLink: {post_data['link']}"
                    await channel.send(message)
                    add_post_to_cache(post_data)
                else:
                    print('Post already alerted.')
            print('Message Sent.')

    @tasks.loop(seconds=21600)
    async def watcher2(self, channel):
        if scrape_fish():
            user_id = config['USER_ID_2']
            message = f"{user_id} \nPrice: {CURR_PRICE} \nLink: {config['URL_2']}"
            await channel.send(message)
            print('Message Sent.')


bot = MyClient(command_prefix='', intents=discord.Intents.all())
bot.run(config['TOKEN'])