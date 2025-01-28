import os
import time
import requests
import asyncio
import discord
import json

from bs4 import BeautifulSoup
from discord.ext import commands, tasks
from dotenv import load_dotenv

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
    "URL_5": os.getenv('URL_5'),
    "URL_6": os.getenv('URL_6'),
    "URL_7": os.getenv('URL_7'),
    "URL_7_PARAMS_VARIABLES": json.loads(os.getenv('URL_7_PARAMS_VARIABLES')),
    "URL_7_PARAMS_EXTENSIONS": json.loads(os.getenv('URL_7_PARAMS_EXTENSIONS')),
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

CACHE = []
CACHE_EXPIRY = 15 * 60  # 15 minutes in seconds
FISH_CURR_PRICE = 329.99
LEVER_CURR_PRICE = 1029.99
MEDAL_OF_HONOR_CURR_PRICE = 19.99
MEDAL_OF_HONOR_DELUXE_CURR_PRICE = 24.99

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
            global FISH_CURR_PRICE
            price = float(price_text[1:])
            if FISH_CURR_PRICE != price:
                FISH_CURR_PRICE = price
                return True

    return False

def scrape_lever():
    print('Scraping Lever')
    url = config['URL_5']
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')

    p_Availablility = soup.find('p', id='_available_stock')
    span_Price = soup.find('span', id='sale_price')

    if p_Availablility and span_Price:
        availability_text = p_Availablility.get_text(strip=True)
        if availability_text != 'Out of Stock':
            global LEVER_CURR_PRICE
            price_text = span_Price.get_text(strip=True)
            price = float(price_text.replace('$', '').replace(',', ''))
            if LEVER_CURR_PRICE != price:
                LEVER_CURR_PRICE = price
                return True

    return False

def scrape_medal_of_honor():
    print('Scraping Medal of Honor')

    backend_url = config['URL_7']
    params = {
        'operationName': 'gameProductsOffers',
        'variables': json.dumps(config['URL_7_PARAMS_VARIABLES']),
        'extensions': json.dumps(config['URL_7_PARAMS_EXTENSIONS'])
    }

    # Send the backend request to fetch the price
    response = requests.get(backend_url, headers=headers, params=params)

    if response.status_code == 200:
        # Extract the displayTotalWithDiscount value
        display_total_with_discount = response.json()['data']['gameProducts']['items'][0]['anonymousOffer']['lowestPricePurchaseOption']['displayTotalWithDiscount']
        display_total_with_discount_deluxe = response.json()['data']['gameProducts']['items'][1]['anonymousOffer']['lowestPricePurchaseOption']['displayTotalWithDiscount']

        # Remove the $ sign and convert to float
        display_total_with_discount = float(display_total_with_discount.replace('$', ''))
        display_total_with_discount_deluxe = float(display_total_with_discount_deluxe.replace('$', ''))

        global MEDAL_OF_HONOR_CURR_PRICE
        global MEDAL_OF_HONOR_DELUXE_CURR_PRICE

        if display_total_with_discount != MEDAL_OF_HONOR_CURR_PRICE or display_total_with_discount_deluxe != MEDAL_OF_HONOR_DELUXE_CURR_PRICE:
            MEDAL_OF_HONOR_CURR_PRICE = display_total_with_discount
            MEDAL_OF_HONOR_DELUXE_CURR_PRICE = display_total_with_discount_deluxe
            return True
    
    return False

class AutoBots(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reddit_watcher.start()
        self.fish_watcher.start()
        self.lever_watcher.start()
        self.medal_of_honor_watcher.start()

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
            message = f"{user_id} \nPrice: {FISH_CURR_PRICE} \nLink: {config['URL_2']}"
            await channel.send(message)
            print('Fish Message Sent.')

    @tasks.loop(seconds=86400)
    async def lever_watcher(channel):
        if scrape_lever():
            user_id = config['USER_ID']
            message = f"{user_id} \nPrice: {LEVER_CURR_PRICE} \nLink: {config['URL_5']}"
            await channel.send(message)
            print('Lever Message Sent.')

    @tasks.loop(seconds=86400)
    async def medal_of_honor_watcher(channel):
        if scrape_medal_of_honor():
            user_id = config['USER_ID']
            message = f"{user_id} \nMedal of Honor Price: {MEDAL_OF_HONOR_CURR_PRICE} \n Medal of Honor Deluxe: {MEDAL_OF_HONOR_DELUXE_CURR_PRICE} \nLink: {config['URL_6']}"
            await channel.send(message)
            print('Medal of Honor Message Sent.')

bot = commands.Bot(command_prefix='/', intents=discord.Intents.all())

@bot.event
async def on_ready():
        channel = bot.get_channel(config['CHANNEL_ID'])
        await bot.tree.sync()
        await asyncio.gather(
            AutoBots.reddit_watcher.start(channel),
            AutoBots.fish_watcher.start(channel),
            AutoBots.lever_watcher.start(channel),
            AutoBots.medal_of_honor_watcher.start(channel)
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