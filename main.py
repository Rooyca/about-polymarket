import os, requests, pytz, json, websockets, asyncio
from dotenv import load_dotenv
from py_clob_client.constants import POLYGON
#from py_clob_client.order_builder.constants import BUY, SELL
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from datetime import datetime, timedelta
from models import Market

load_dotenv()

# CONSTANTS
CLOB_ENDPOINT = "https://clob.polymarket.com"
GAMMA_ENDPOINT = 'https://gamma-api.polymarket.com'
WSS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws"
DATA_API_ENDPOINT = "https://data-api.polymarket.com"
REQUESTS_TIMEOUT = 30
CHAIN_ID = POLYGON

# ENVIRONMENT VARIABLES
KEY = os.getenv("PK") or "" # Private Key
FUNDER = os.getenv("FUNDER") or "" # Wallet Address
MARKET_LIQUIDITY_THRESHOLD = int(os.getenv("MARKET_LIQUIDITY_THRESHOLD") or 10000)
MARKET_VOLUME_THRESHOLD = int(os.getenv("MARKET_VOLUME_THRESHOLD") or 10000)
MARKET_TIME_THRESHOLD = int(os.environ.get("MARKET_TIME_THRESHOLD", 24))
LIMIT = int(os.environ.get("LIMIT", 300))

# Create CLOB Client
client = ClobClient(
			CLOB_ENDPOINT,
			key=KEY,
			chain_id=CHAIN_ID,
			funder=FUNDER,
			signature_type=1,
		)
client.set_api_creds(client.create_or_derive_api_creds())

def fetch_active_markets():
	"""Fetch active markets"""
	try:
		min_end_date = datetime.now(pytz.UTC) + timedelta(hours=MARKET_TIME_THRESHOLD)
		params = {
			"limit": 300,
			"offset": 0,
			"order": "volume",
			"ascending": False,
			"active": True,
			"closed": False,
			"tag_id": 1, # Sports
			"tag_id": 100639, # Games
			"related_tags": True,
			"liquidity_num_min": MARKET_LIQUIDITY_THRESHOLD,
			"end_date_max": min_end_date.isoformat(),
			"volume_num_min": MARKET_VOLUME_THRESHOLD,
		}
		response = requests.get(f"{GAMMA_ENDPOINT}/markets", params=params, timeout=REQUESTS_TIMEOUT)
		response.raise_for_status()
		return parse_market_data(response.json())
	except:
		return []

def parse_market_data(markets_data):
	"""Parse and validate market data"""
	filtered = []
	for market_data in markets_data:
		try:
			for field in ["outcomes", "outcomePrices", "clobTokenIds"]:
				if isinstance(market_data.get(field), str):
					try:
						market_data[field] = json.loads(market_data[field])
					except json.JSONDecodeError:
						market_data[field] = market_data[field].strip("[]").replace('"', "").split(",")
			
			market = Market(**{
				**market_data,
				"fee": market_data.get("fee", 0.0),
				"image": market_data.get("image", ""),
				"icon": market_data.get("icon", ""),
				"description": market_data.get("description", "")
			})
		
			if valid_odds(market):
				filtered.append(market)
			market = [market for market in filtered if "vs. " in market.question]
			market = [market for market in filtered if market.enable_order_book]

		except:
			pass
	return filtered

def valid_odds(market):
	"""Validate market odds"""
	if len(market.outcome_prices) < 2:
		return False
	yes_odds = market.outcome_prices[0]
	no_odds = market.outcome_prices[1]
	return 0.10 < yes_odds < 0.90 and 0.10 < no_odds < 0.90

def fetch_live_market_data(slug_event):
	"""Fetch live data"""
	try:
		response = requests.get(f"{GAMMA_ENDPOINT}/markets?slug={slug_event}", timeout=REQUESTS_TIMEOUT)
		response.raise_for_status()
		return response.json()
	except:
		return None

def load_market_data(market):
	"""
	Fetches and processes live market data for a given market
	"""
	labels = {
		"question": "",
		"outcomes": "",
		"spread": "",
		"outcomePrices": "",
		"score": "",
		"elapsed": "",
		"period": "",
		"liquidity": ""
	}

	try:
		raw_data = fetch_live_market_data(market.slug)
		
		if not raw_data or not isinstance(raw_data, list):
			return labels

		# Extract primary data container
		primary_data = raw_data[0]
		
		# Find market data in either 'markets' array or root object
		market_data = (
			primary_data["markets"][0] 
			if "markets" in primary_data and primary_data["markets"]
			else primary_data
		)

		# Directly map values from combined sources
		combined = {**market_data, **{
			field: primary_data.get(field, "")
			for field in ["question", "score", "elapsed", "period", "liquidity"]
		}}

		# Single-pass population of labels with type conversion
		labels.update({
			key: str(combined.get(key, "")) 
			for key in labels
		})

	except (KeyError, IndexError) as e:
		print(f"Data structure mismatch: {e}")
	except Exception as e:
		print(f"Unexpected error: {e}")

	return labels


def load_positions():
	try:
		response = requests.get(f"{DATA_API_ENDPOINT}/positions?sizeThreshold=.1&user={FUNDER}")
		response.raise_for_status()
		positions = response.json()
		
		for position in positions:
			print(f"""
				Title: {position['title']}\n
				Shares: {position['shares']}\n
				Initial Value: {position['initialValue']}\n
				Current Value: {position['currentValue']}\n
				"""
			)
	except Exception as e:
		print(f"Error: {str(e)}")
		
def load_orders():
	try:
		open_orders = client.get_orders()
		
		for order in open_orders:
			print(f"""
				ID: {order["id"]}
				Outcome: {order["outcome"]}
				Side: {order["side"]}
				Price: {order["price"]}
				Size: {order["original_size"]}
				Filled: {order["size_matched"]}
			""") #order["expiration"]
	except Exception as e:
		print(f"Error: {str(e)}")


def cancel_order(or_id):
	try:
		client.cancel(order_id=or_id)
		print("Success", "Order cancelled successfully")
	except Exception as e:
		print(f"Error: Failed to cancel order: {str(e)}")

def cancel_orders():
	try:
		client.cancel_all()
		print("Success: Orders cancelled successfully")
	except Exception as e:
		print(f"Error: Failed to cancel orders: {str(e)}")


def place_order(token_id, price, size, side):
	try:
		side = side.upper()
		order_place = client.create_and_post_order(OrderArgs(
			price=price,
			size=size,
			side=side,
			token_id=token_id,
		))
		print(f"[+] Order Placed: Order successfully placed!\n{order_place}")
	except Exception as e:
		print(f"[-] Order Error: Failed to place order: {str(e)}")

###
#
#  WEBSOCKET
#
###

def start_websocket(market_id):
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)
	loop.run_until_complete(subscribe_and_display_order_book(market_id))

async def subscribe_and_display_order_book(market_id):
	try:
		async with websockets.connect(f"{WSS_ENDPOINT}/market") as websocket:
			await websocket.send(json.dumps({"type": "market", "assets_ids": [market_id]}))
			while True:
				message = await websocket.recv()
				data = json.loads(message)
				try:
					update_order_book(data[0])
				except:
					pass
	except Exception as e:
		print(f"Error: WebSocket error: {str(e)}")

def update_order_book(order_data):
	# Initialize dictionaries if they don't exist
	if not hasattr(order_data, 'current_bids'):
		current_bids = {}
	if not hasattr(order_data, 'current_asks'):
		current_asks = {}

	event_type = order_data.get('event_type')
	
	if event_type == 'book':
		# Full order book snapshot
		current_bids = {bid['price']: bid['size'] for bid in order_data['bids']}
		current_asks = {ask['price']: ask['size'] for ask in order_data['asks']}
	elif event_type == 'price_change':
		# Process incremental updates
		for change in order_data.get('changes', []):
			price = change['price']
			size = change['size']
			side = change['side'].upper()
			
			target = current_bids if side == 'BUY' else current_asks
			
			if size == '0':
				target.pop(price, None)
			else:
				target[price] = size
	else:
		return  # Unknown event type
	
	# Sort and display bids (descending by price)
	for price, size in sorted(current_bids.items(),
							 key=lambda x: float(x[0]), 
							 reverse=True):
		print(f"BID: {size} @ {price}")
	
	# Sort and display asks (ascending by price)
	for price, size in sorted(current_asks.items(),
							 key=lambda x: float(x[0])):
		print(f"ASK: {size} @ {price}")

# markets = fetch_active_markets()[0]
# print(start_websocket(markets.clob_token_ids[0])) # Token for First outcome