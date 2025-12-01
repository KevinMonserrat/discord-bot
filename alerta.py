import json
#import asyncio
from web3 import Web3
from discord.ext import tasks
from dotenv import load_dotenv
import os
from embeds import embed_tx

load_dotenv()

# ===========================
# CONFIG
# ===========================
apikey = os.getenv("INFURA")
INFURA_URL = f"https://mainnet.infura.io/v3/{apikey}"
w3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Direcciones de stablecoins (mainnet)
STABLECOINS = {
    "USDT": Web3.to_checksum_address("0xdAC17F958D2ee523a2206206994597C13D831ec7"),
    "USDC": Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "DAI": Web3.to_checksum_address("0x6B175474E89094C44Da98b954EedeAC495271d0F")
}
decimals = {
    "USDT" : 6,
    "USDC" : 6,
    "DAI" : 18
}
ABI_ERC20 = [ #parte del abi del evento transfer para crear el eth.contract y poder usar .events.funciondelabi
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    }
]

ARCHIVO = "monitoreos.json"

# estructura: { user_id: { wallet: "0x..": { stablecoin, last_block } } }
monitoreos = {}


# ============================================================
# LECTURA / ESCRITURA ARCHIVO
# ============================================================

def cargar_monitoreos(): #lee el json y se guarda en monitoreos{}
    global monitoreos
    try:
        with open(ARCHIVO, "r") as f:
            monitoreos = json.load(f)
    except:
        monitoreos = {}


def guardar_monitoreos():
    with open(ARCHIVO, "w") as f:
        json.dump(monitoreos, f, indent=4) #guardamos monitoreos en el archivo


def iniciar_monitoreo(user_id, wallet, stablecoin, minimo):
    user_id = str(user_id) 

    if user_id not in monitoreos: #si no esta la id en el archivo se guarda
        monitoreos[user_id] = {}

    monitoreos[user_id][wallet] = { #a la wallet le asignamos un dict con stablecoin y ultimobloque
        "stablecoin": stablecoin,
        "minimo":minimo,
        "last_block": w3.eth.block_number #devuelve el ultimo bloque de la red ?ethereum?
    }

    guardar_monitoreos()


def detener_monitoreo(user_id, wallet):
    user_id = str(user_id)

    if user_id in monitoreos and wallet in monitoreos[user_id]: #si esta el user y su wallet, los borramos
        del monitoreos[user_id][wallet]

    guardar_monitoreos()




RANGO = 3000   # bloques por página (seguro para Mainnet)


@tasks.loop(seconds=15)
async def loop_monitoreo(bot):
    global monitoreos

    if not monitoreos:
        return

    for user_id, wallets in monitoreos.items():#id, wallet, (.items devuelve los items de un dict)

        # usuario de Discord
        try:
            user = await bot.fetch_user(int(user_id))
        except:
            continue

        for wallet, data in wallets.items(): #por cada wallet, data en wallets
            stablecoin = data["stablecoin"] #guardo la stable
            last_block = data["last_block"] #guardo el ultimo bloque
            minimo = data["minimo"]

            token_addr = STABLECOINS[stablecoin] #dir del token
            token = w3.eth.contract(address=token_addr, abi=ABI_ERC20)#

            current_block = w3.eth.block_number
            desde = last_block + 1 #el siguiente bloque despues del ultimo leido, para evitar repetir lo que ya leimos del ultimo
            hasta = current_block #bloque actual

            if desde > hasta: #si desde es mayor a hasta
                continue


            bloque_inicio = desde

            while bloque_inicio <= hasta: #mientras el inicio sea menor o igual al final
                bloque_fin = min(bloque_inicio + RANGO, hasta) #retorna el mas pequeño de los dos argumentos que les pasemos

                try:
                    events = token.events.Transfer().get_logs( #agarramos los logs de transfer desde los bloques que les pasamos
                        from_block=bloque_inicio,
                        to_block=bloque_fin
                    )

                except Exception as e:
                    print("Error leyendo logs:", e)
                    break

                # procesar eventos
                for ev in events: #por cada transfer
                    _from = ev["args"]["from"]
                    _to = ev["args"]["to"]
                    value = ev["args"]["value"] / (10 ** decimals[stablecoin])
                    tx_hash = ev["transactionHash"].hex()
                    
                    if value < minimo:
                        continue # pasamos a la sig tx

                    if wallet.lower() in (_from.lower(), _to.lower()):#si la wallet esta en el from o en el to
                        mensaje = (
                            f"**Transferencia de {stablecoin}**\n\n"
                            f"En la wallet: {wallet}\n\n"
                            f"De: {_from}\n"
                            f"A: {_to}\n\n"
                            f"Monto: {value} de {stablecoin}\n\n"
                            f"[Ver en Etherscan](https://etherscan.io/tx/{tx_hash})"
                        )
                        try:
                            await user.send(embed=embed_tx(mensaje))
                        except:
                            print("No pude enviar DM al usuario", user_id)

                
                bloque_inicio = bloque_fin + 1 # ahora el bloque final va a ser el de inicio +1

            
            monitoreos[user_id][wallet]["last_block"] = current_block# actualizar ultimo bloque leido

    guardar_monitoreos()
