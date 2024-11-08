import requests
import asyncio
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
    "URL_4": os.getenv('URL_4')
}

CACHE = []
CACHE_EXPIRY = 15 * 60  # 15 minutes in seconds
CURR_PRICE = 329.99

def scrape_reddit():
    url = config['URL']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title_elements = soup.find_all('a', class_='block font-semibold text-neutral-content-strong m-0 visited:text-neutral-content-weak text-16 xs:text-18 mb-2xs xs:mb-xs overflow-hidden')

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

# Custom scraper for the ebay
def scrape_ebay():
    url = config['URL_3']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find the price
    price_span = soup.find_all('span', class_='ux-textspans ux-textspans--BOLD ux-textspans--EMPHASIS')

    if price_span and len(price_span) == 2 and price_span[1].text.strip() == 'Out of Stock':
        return False

    return True

# Custom scraper for the a barrel
def scrape_barrel():
    url = config['URL_4']
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    availability = [div.get('class', []) for div in soup.find_all('div', attrs={'title': 'Availability'})]

    if availability[0][1] == 'available':
        return True

    return False

class AutoBots(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reddit_watcher.start()
        self.fish_watcher.start()
        self.barrel_watcher.start()

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

    @tasks.loop(seconds=21600)
    async def fish_watcher(channel):
        if scrape_fish():
            user_id = config['USER_ID_2']
            message = f"{user_id} \nPrice: {CURR_PRICE} \nLink: {config['URL_2']}"
            await channel.send(message)
            print('Fish Message Sent.')

    @tasks.loop(seconds=21600)
    async def ebay_watcher(channel):
        if scrape_ebay():
            user_id = config['USER_ID_2']
            message = f"{user_id} \nPatch In Stock! \nLink: {config['URL_3']}"
            await channel.send(message)
            print('Patch Message Sent.')
    
    @tasks.loop(seconds=60)
    async def barrel_watcher(channel):
        if scrape_barrel():
            user_id = config['USER_ID']
            message = f"{user_id} \nBarrel In Stock! \nLink: {config['URL_4']}"
            await channel.send(message)
            print('Barrel Message Sent.')

bot = commands.Bot(command_prefix='/', intents=discord.Intents.all())

@bot.event
async def on_ready():
        channel = bot.get_channel(config['CHANNEL_ID'])
        await bot.tree.sync()
        await asyncio.gather(
            AutoBots.reddit_watcher.start(channel),
            AutoBots.fish_watcher.start(channel),
            AutoBots.barrel_watcher.start(channel)
        )

@bot.hybrid_command(name='utils')
async def utils(ctx: commands.Context, ebill: str):
    internetBill = 70
    electricityBill = float(ebill)

    iBillSplit = round(internetBill / 4, 2)
    eBillSplit = round(electricityBill / 4, 2)

    eachBill = iBillSplit + eBillSplit

    ourBillHalf = round(eBillSplit * 2, 2) - round(iBillSplit * 2, 2)

    await ctx.send(f'Internet Bill Each: {iBillSplit} \nElectricity Bill Each: {eBillSplit} \nBills Split Four Ways: {eachBill} \nOur Bill: {ourBillHalf}')

bot.run(config['TOKEN'])