from collections.abc import Callable
from cdp import Wallet
from pydantic import BaseModel, Field
from cdp_agentkit_core.actions import CdpAction
from cdp_agentkit_core.actions.wow.utils import get_buy_quote, get_sell_quote
from cdp_agentkit_core.actions.wow.constants import WOW_ABI
from web3 import Web3

# @TODO: escrow_address needed! 
# @TODO : add redeemGift.py to handle recipient decisions, including memecoin or USDC transfers.
# @TODO : fill in get_current_usdc_price with real price and...should be more careful abt base / eth / usdc / memecoin pricing 


GIFT_ESCROW_ABI = [
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "recipient", "type": "address"},
            {"name": "giver", "type": "address"},
            {"name": "redeemableUsdcAmount", "type": "uint256"},
            {"name": "initialBuyPrice", "type": "uint256"}
        ],
        "name": "createGift",
        "outputs": [{"name": "giftId", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "giftId", "type": "uint256"},
            {"name": "choice", "type": "uint8"}  # 0 for memecoin, 1 for USDC
        ],
        "name": "redeemGift",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

GIFT_TRANSFER_PROMPT = """
This tool enables gift transfer of a memecoin with a fixed USDC redemption option. The sender buys 
the memecoin which is locked in escrow, and the recipient can choose to either:
1. Receive the memecoin
2. Receive the fixed USDC amount (equal to sender's initial buy price)
An NFT receipt is minted upon redemption showing whether the sender profited or lost based on 
the memecoin's current value."""

class GiftTransferInput(BaseModel):
    """Input argument schema for gift transfer action."""
    amount_eth_in_wei: str = Field(
        ..., 
        description="Amount of ETH to spend on memecoin (in wei)"
    )
    memecoin_address: str = Field(
        ...,
        description="The memecoin token address to purchase and gift"
    )
    recipient: str = Field(
        ...,
        description="The address to receive the gift"
    )
    giver: str = Field(
        ...,
        description="The address sending the gift"
    )

def gift_transfer(
    wallet: Wallet,
    amount_eth_in_wei: str,
    memecoin_address: str, 
    recipient: str,
    giver: str
) -> str:
    """Create a gift transfer with fixed USDC redemption option.

    Args:
        wallet: The wallet to transfer from
        amount_eth_in_wei: Amount of ETH to spend on memecoin
        memecoin_address: The memecoin token address
        recipient: Recipient's address
        giver: Address sending the gift

    Returns:
        str: Message with transfer details and redemption info
    """
    try:
        # 1. Get quote for memecoin purchase
        token_quote = get_buy_quote(
            wallet.network_id,
            memecoin_address,
            amount_eth_in_wei
        )

        # Calculate platform fee (3%)
        platform_fee = int(float(amount_eth_in_wei) * 0.03)
        total_eth_required = str(int(amount_eth_in_wei) + platform_fee)

        # 2. Buy memecoin and lock in escrow
        escrow_address = "0x..."  # Would come from config
        # escrow_address = fetch_escrow_address(wallet.network_id)  # Fetch dynamically

        # Approve escrow to handle the memecoin
        buy_result = wallet.invoke_contract(
            contract_address=memecoin_address,
            method="buy",
            abi=WOW_ABI,
            args={
                "recipient": escrow_address,
                "refundRecipient": wallet.default_address.address_id,
                "orderReferrer": "0x0000000000000000000000000000000000000000",
                "expectedMarketType": "0",
                "minOrderSize": str(int(float(token_quote) * 0.99)),  # 1% slippage
                "sqrtPriceLimitX96": "0",
                "comment": f"Gift purchase for {recipient}"
            },
            amount=total_eth_required,
            asset_id="wei"
        ).wait()

        # Get current USDC value of purchase
        usdc_price = get_current_usdc_price(wallet.network_id, memecoin_address, token_quote)

        # 3. Create gift in escrow with fixed USDC redemption value
        gift_result = wallet.invoke_contract(
            contract_address=escrow_address,
            method="createGift",
            abi=GIFT_ESCROW_ABI,
            args={
                "token": memecoin_address,
                "recipient": recipient,
                "giver": giver,
                "redeemableUsdcAmount": usdc_price,
                "initialBuyPrice": amount_eth_in_wei
            }
        ).wait()

        return (
            f"Created gift transfer with fixed USDC redemption:\n"
            f"- Purchased {token_quote} tokens of {memecoin_address}\n"
            f"- From: {giver}\n"
            f"- To: {recipient}\n"
            f"- Initial ETH spent: {Web3.from_wei(int(amount_eth_in_wei), 'ether')} ETH\n"
            f"- Platform fee: {Web3.from_wei(platform_fee, 'ether')} ETH\n"
            f"- Fixed USDC redemption value: {usdc_price / 1e6} USDC\n"
            f"- Recipient can choose to receive either:\n"
            f"  1. The memecoin tokens\n"
            f"  2. The fixed USDC amount\n"
            f"Gift creation tx: {gift_result.transaction_hash}\n"
            f"Transaction link: {gift_result.transaction_link}"
        )

    except Exception as e:
        return f"Error in gift transfer: {str(e)}"

def get_current_usdc_price(network_id: str, memecoin_address: str, token_amount: int) -> int:
    """Get current USDC value for token amount."""
    # This would integrate with a real price feed
    # For now returning a mock calculation
    eth_price_in_usdc = 2000  # Mock ETH/USDC price
    sell_quote = get_sell_quote(network_id, memecoin_address, str(token_amount))
    usdc_value = int((float(sell_quote) / 1e18) * eth_price_in_usdc * 1e6)
    return usdc_value



class GiftTransferAction(CdpAction):
    """Gift transfer action with fixed USDC redemption option."""
    name: str = "gift_transfer"
    description: str = GIFT_TRANSFER_PROMPT
    args_schema: type[BaseModel] | None = GiftTransferInput
    func: Callable[..., str] = gift_transfer

    