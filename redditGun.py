import os
import re
import subprocess
import time
import requests
import asyncio
import discord
import json

from bs4 import BeautifulSoup
from discord.ext import commands, tasks
from dotenv import load_dotenv
from icecream import ic

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
    "URL_3": os.getenv('URL_3'),
    "NEW_OTHER_KEYWORDS": os.getenv('NEW_OTHER_KEYWORDS').split(','),
    "URL_5": os.getenv('URL_5'),
    "IP": os.getenv('IP'),
    "URL_6": os.getenv('URL_6')
}

ic(config)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

CACHE = []
CACHE_EXPIRY = 120 * 60  # 15 minutes in seconds
FISH_CURR_PRICE = 199.99
CURR_IP = config['IP']

def scrape_reddit():
    url = config['URL']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    title_elements = soup.find_all('a', class_='block text-neutral-content-strong m-0 visited:text-neutral-content-weak font-semibold text-16-scalable xs:text-18-scalable mb-2xs xs:mb-xs overflow-hidden')

    keywords = config['KEYWORDS']
    otherKeywords = config['OTHER_KEYWORDS']

    titles = []
    base_url = "https://www.reddit.com"
    ic(title_elements)
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

def scrape_reddit2():
    url = config['URL_3']
    response = requests.get(url)

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all title elements
    title_elements = soup.find_all('a', class_='block text-neutral-content-strong m-0 visited:text-neutral-content-weak font-semibold text-14 xs:text-16 mb-xs overflow-hidden')
    newOtherKeywords = config['NEW_OTHER_KEYWORDS']

    titles = []
    base_url = "https://www.reddit.com"
    for title_element in title_elements:
        #grab the title text and shorten it from [H] to [W]
        if title_element.has_attr('slot') and title_element['slot'] == 'title':
            title = title_element.text
            match = re.search(r'\[H\](.*?)\[W\]', title, re.IGNORECASE | re.DOTALL)
            if match:
                between_hw = match.group(1).strip()
                if any(otherKeyword.lower() in between_hw.lower() for otherKeyword in newOtherKeywords):
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
            global FISH_CURR_PRICE
            price = float(price_text[1:])
            if FISH_CURR_PRICE != price:
                FISH_CURR_PRICE = price
                return True

    return False

def scrape_patch():
    url = config['URL_5']
    file_name = 'patch.html'

    curl_command = [
        'curl', '-o', file_name, url
    ]

    subprocess.run(curl_command)

    # Read the HTML file with BeautifulSoup
    with open(file_name, 'r') as file:
        soup = BeautifulSoup(file, 'html.parser')

    os.remove(file_name)

    button = soup.find('button', id='ProductSubmitButton-template--23839774408987__main')

    if button:
        span = button.find('span')
        if span:
            span_text = span.text.strip()
            return span_text != "Sold out"

    return False

def scrape_gpu():
    urls = [
        'https://www.zotacstore.com/us/zotac-gaming-geforce-rtx2080ti-11gb-gddr6-refurbished',
        'https://www.zotacstore.com/us/zotac-gaming-geforce-rex2080ti-11gb-gddr6-refurbished',
        'https://www.zotacstore.com/us/zotac-gaming-geforce-rtx2080ti-11gb-gddr6-352-bit-refurbished'
    ]

    data = []

    for url in urls:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        product_info = soup.find('div', class_='product-info-stock-sku')
        if product_info:
            stock_status = product_info.find('div', class_='stock available')
            if stock_status:
                data.append(url)

    return data

def scrape_ip():
    global CURR_IP

    response = requests.get('https://api.ipify.org?format=json')
    if response.status_code == 200:
        if response.json()['ip'] != CURR_IP:
            CURR_IP = response.json()['ip']
            return True

    return False

def scrape_trigger():
    url = config['URL_6']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    meta = soup.find('meta', itemprop='availability')

    if meta and meta.has_attr('content'):
        return meta['content'] == "http://schema.org/InStock"

    return False

class AutoBots(commands.Bot):
    @tasks.loop(seconds=20)
    async def reddit_watcher(channel):
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
            print('Reddit Message Sent.')
        
    @tasks.loop(seconds=20)
    async def reddit_watcher2(channel):
        posts = scrape_reddit2()
        if posts:
            for post_data in posts:
                if not is_post_alerted(post_data):
                    user_id = config['USER_ID']
                    message = f"{user_id} \nTitle: {post_data['title']} \nLink: {post_data['link']}"
                    await channel.send(message)
                    add_post_to_cache(post_data)
                else:
                    print('Post already alerted.')
            print('Second Reddit Message Sent.')

    @tasks.loop(seconds=21600)
    async def fish_watcher(channel):
        if scrape_fish():
            user_id = config['USER_ID_2']
            message = f"{user_id} \nPrice: {FISH_CURR_PRICE} \nLink: {config['URL_2']}"
            await channel.send(message)
            print('Fish Message Sent.')

    @tasks.loop(seconds=86400)
    async def patch_watcher(channel):
        if scrape_patch():
            user_id = config['USER_ID']
            message = f"{user_id} \nPatch in stock! \nLink: {config['URL_5']}"
            await channel.send(message)
            print('Patch Message Sent.')

    @tasks.loop(seconds=3600)
    async def gpu_watcher(channel):
        gpuData = scrape_gpu()
        if len(gpuData) > 0:
            user_id = config['USER_ID']
            message = f"{user_id} \nZotac GPU Available \nLink: {gpuData}"
            await channel.send(message)
            print('GPU Message Sent.')

    @tasks.loop(seconds=86400)
    async def ip_watcher(channel):
        if scrape_ip():
            user_id = config['USER_ID']
            message = f"{user_id} \nNew IP: {CURR_IP}"
            await channel.send(message)
            print('IP Update Message Sent.')

    @tasks.loop(seconds=86400)
    async def trigger_watcher(channel):
        if scrape_trigger():
            user_id = config['USER_ID']
            message = f"{user_id} \nTrigger in stock! \nLink: {config['URL_6']}"
            await channel.send(message)
            print('Trigger Message Sent.')

bot = commands.Bot(command_prefix='/', intents=discord.Intents.all())

@bot.event
async def on_ready():
        channel = bot.get_channel(config['CHANNEL_ID'])
        await bot.tree.sync()
        await asyncio.gather(
            AutoBots.reddit_watcher.start(channel),
            # AutoBots.reddit_watcher2.start(channel),
            AutoBots.fish_watcher.start(channel),
            AutoBots.patch_watcher.start(channel),
            AutoBots.gpu_watcher.start(channel),
            AutoBots.ip_watcher.start(channel),
            AutoBots.trigger_watcher.start(channel)
        )

@bot.hybrid_command(name='utils')
async def utils(ctx: commands.Context, ebill: str):
    internetBill = 60
    electricityBill = float(ebill)

    iBillSplit = round(internetBill / 4, 2)
    eBillSplit = round(electricityBill / 4, 2)

    eachBill = iBillSplit + eBillSplit

    ourBillHalf = round(eBillSplit * 2, 2) - round(iBillSplit * 2, 2)

    await ctx.send(f'Internet Bill Each: {iBillSplit} \nElectricity Bill Each: {eBillSplit} \nBills Split Four Ways: {eachBill} \nOur Bill: {ourBillHalf}')

@bot.hybrid_command(name='ip')
async def ip(ctx: commands.Context):
    response = requests.get('https://api.ipify.org?format=json')
    if response.status_code == 200:
        ip_data = response.json()
        await ctx.send(f"Current IP: {ip_data['ip']}")
    else:
        await ctx.send('Failed to retrieve IP address.')

bot.run(config['TOKEN'])