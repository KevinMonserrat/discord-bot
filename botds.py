import discord
import os #env
from discord.ext import commands, tasks
from discord import app_commands
import requests #llamadas HTTP sincronicas
from dotenv import load_dotenv #env
import logging
from functions1 import autocomplete_wallets, autocomplete_stablecoin, autocomplete_minimo
import func_wallets
import embeds
from web3 import AsyncWeb3, Web3
import asyncio
from alerta import iniciar_monitoreo, detener_monitoreo, loop_monitoreo, cargar_monitoreos, guardar_monitoreos


#seteo del bot
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')#guarda los logs en discord.log en utf-8, abriendo el archivo en modod escritura
intents = discord.Intents.default() #variable intents con permisos por defecto
intents.message_content = True #activamos el intents de message_content para que lea los mensajes y los comandos funcionen correctamente, debe estar activado tambien en discorddeveloperportal
bot = commands.Bot(command_prefix = commands.when_mentioned_or('$'), intents=intents) #como empiezan los comandos para el bot, o cuando sea mencionado

#variables de entorno
load_dotenv()#cargamos el .env, de las variables de entorno
TOKEN = os.getenv("TOKEN")#busca el string de TOKEN y lo guardamos en Token, o tambien podemos hacer TOKEN = otroarchivo.TOKEN
apikey = os.getenv("APIKEY")
api_infura = os.getenv("INFURA")
api_alchemy = os.getenv("ALCHEMY")

#conexiones
conexionhttp = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(f"https://mainnet.infura.io/v3/{api_infura}")) #~usamos para las solicitudes
conexion_sincro = Web3(Web3.HTTPProvider(f"https://mainnet.infura.io/v3/{api_infura}"))

url_etherscan = "https://api.etherscan.io/v2/api"
monitor_activo = False


#variables para monitoreo
#last_data = {} #user_id : {wallet: {"eth":balance_eth, "txs": {token: [hash1, hash2]}}}
tokens = {  # Contratos de stablecoins
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "DAI":  "0x6B175474E89094C44Da98b954EedeAC495271d0F"
}
usuarios_activos = set()#construye un coleccion de elementos unicos sin orden


@bot.event #sincronizamos los comandos tree(slash /)
async def setup_hook():
    synced = await bot.tree.sync()
    print(f"Se sincronizaron {len(synced)} comandos slash correctamente.")

#comandos hibridos que funcionan con /, el prefijo o cuando mencionas al bot
@bot.hybrid_command(description="Agrega una wallet de la red ETH") #lo que aparece abajo del comando /nombredelcomando
@app_commands.describe(wallet="Dirección de la wallet")#lo que aparece cuando hay que agregar el parametro wallet
async def agregarwallet(ctx: commands.Context, wallet:str): #commands.Context no es obligatorio, solo ayuda a entender mejor el codigo lo mismo con wallet, deberia ser un str
    user_id = ctx.author.id
    try:
        agregado = func_wallets.agregar_wallet(user_id, wallet)
        if agregado:
            await ctx.send(embed = embeds.embed_exito(f"Wallet de {ctx.author} registrada correctamente."))
        else:
            await ctx.send(embed=embeds.embed_error("Esta wallet ya se encuentra registrada."))
    except Exception as e:
        await ctx.send(embed = embeds.embed_error(f"Ocurrio un error: {e}"))




@bot.hybrid_command(description="Elimina una de tus wallet")
@app_commands.describe(wallet="Direccion de la wallet a eliminar")
@app_commands.autocomplete(wallet=autocomplete_wallets)
async def eliminarwallet(ctx, wallet: str):
    user_id = ctx.author.id
    resultado = func_wallets.borrar_wallet(user_id, wallet)#la funcion devuelve un string en base a si existe la wallet o no.
    
    if (resultado).endswith("correctamente."):
        await ctx.send(embed = embeds.embed_exito(resultado))#devolvemos el string que indica si todo salio bien
    else:
        await ctx.send(embed = embeds.embed_error(resultado))




@bot.hybrid_command(description="Ver tus wallets guardadas")
async def verwallets(ctx):
    data = func_wallets.cargar_wallets()
    user_id = str(ctx.author.id)

    if user_id in data and len(data[user_id]) > 0:
        mensaje = "\n\n ".join(data[str(ctx.author.id)])
        return await ctx.send(embed=embeds.embed_exito(mensaje))
    
    await ctx.send(embed=embeds.embed_error("No tenés wallets guardadas"))



@bot.hybrid_command(name="balance", description="Consultar balance")
@app_commands.describe(wallet="Selecciona una de tus wallets")
@app_commands.autocomplete(wallet=autocomplete_wallets)
async def balance(ctx, wallet : str):
    data = func_wallets.cargar_wallets()
    user_id = str(ctx.author.id)

    try:
        wallet = func_wallets.normalizar(wallet)
    except Exception:
        await ctx.send(embed=embeds.embed_error("Direccion invalida"))
    #print("Infura conectado", await conexionhttp.is_connected())

    if user_id not in data: #si el usuario no esta registrado
        return await ctx.send(embed = embeds.embed_error("No estas registrado en el sistema"))    
    
    normalized_wallets = [func_wallets.normalizar(w) for w in data[user_id]]

    if wallet not in normalized_wallets:
        return await ctx.send(embed=embeds.embed_error("No tenés esa wallet registrada"))
    
    balance = await conexionhttp.eth.get_balance(wallet)
    balanceeth = conexionhttp.from_wei(balance, "ether")

    await ctx.send(embed = embeds.embed_exito(f"Balance de {wallet}:\n{balanceeth} ETH"))




#error:no se actualizan las txs
@bot.hybrid_command(name="transferencias", description="Ver transferencias de stablecoins(USDT,USDC y DAI)")
@app_commands.describe(wallet= "Selecciona una de tus wallets", token="Selecciona un token")
@app_commands.autocomplete(wallet=autocomplete_wallets, token =autocomplete_stablecoin)
async def transferencias(ctx, wallet:str, token):

    await ctx.defer()#si el comando tarda mas de  3segs, ya que al mostrar 10 transf tarda mas, sino da como error
    data = func_wallets.cargar_wallets()
    user_id = str(ctx.author.id)
    # Normalizar direccion ingresada
    try:
        wallet = func_wallets.normalizar(wallet) #otra vez usamos los checksum
    except Exception:
        return await ctx.send(embed=embeds.embed_error("Dirección inválida"))
    
    normalized_wallets = [func_wallets.normalizar(w) for w in data[user_id]]
    
    if wallet not in normalized_wallets:
        return await ctx.send(embed=embeds.embed_error("No tenés esa wallet registrada"))
    tokens = {#dir de contratos
        "USDT":"0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC":"0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI":"0x6B175474E89094C44Da98b954EedeAC495271d0F"
    }
    if token not in tokens :
        return await ctx.send(embed = embeds.embed_error("Token invalido"))
   
    contrato = tokens[token]

    params = {
        "apikey": apikey,
        "chainid": "1",
        "module": "account",
        "action": "tokentx",
        "contractaddress": contrato,
        "address": wallet,
        "sort": "desc"  # mas recientes antes
    }
    request = requests.get(url_etherscan, params=params)
    data_api = request.json()
    result = data_api.get("result")
    if not isinstance(result, list):#si no es lista
        return await ctx.send(embed = embeds.embed_error("No se encontraron transferencias."))
    
    if len(result) == 0:
        return await ctx.send(embed = embeds.embed_error("No se encontraron transferencias."))
    mensaje = ""
    for transf in data_api["result"][:10]:
        cant = int(transf["value"]) / (10 ** int(transf["tokenDecimal"])) #10 elevado a los decimales
        tipo = "Recibido" if transf["to"].lower() == wallet.lower() else "Enviado"


        mensaje +=(
            f"{token} - {tipo}\n"
            f"Cantidad: `{cant}`\n"
            f"[Tx Hash](https://etherscan.io/tx/{transf['hash']})\n\n"#separamos con 2 enters la siguiente tx
        )
    await ctx.send(embed=embeds.embed_exito(mensaje))




# comando para activar monitoreo
@bot.tree.command(name="activar_monitoreo", description="Activa el monitoreo de una wallet y una stablecoin.")
@app_commands.autocomplete(wallet=autocomplete_wallets, stablecoin=autocomplete_stablecoin, minimo=autocomplete_minimo)
async def activar_monitoreo(interaction: discord.Interaction, wallet: str, stablecoin: str, minimo:int = 0 ):#0 valor por defecto
    
    await interaction.response.send_message(embed=embeds.embed_exito(
        f"Monitoreo activado\n  Wallet: {wallet}\n Stablecoin: {stablecoin}\n Minimo: {minimo}\n"
    ) ,ephemeral=True )

    user_id = interaction.user.id
    try:
        minimo = float(minimo)
    except:
        minimo = 0

    iniciar_monitoreo(user_id, wallet, stablecoin, minimo)

# Comando para detener monitoreo
@bot.tree.command(name="detener_monitoreo", description="Detiene el monitoreo de una wallet.")
@app_commands.autocomplete(wallet=autocomplete_wallets)
async def detener_monitoreo_cmd(interaction: discord.Interaction, wallet: str):

    detener_monitoreo(interaction.user.id, wallet)
    
    await interaction.response.send_message(
        f"⛔ Monitoreo detenido para {wallet}.",
        ephemeral=True
    )

# Cuando el bot arranca, cargar monitoreos y lanzar loop si es necesario
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

    cargar_monitoreos()

    # si el loop no está corriendo, iniciarlo
    if not loop_monitoreo.is_running():
        loop_monitoreo.start(bot)

    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error al sincronizar slash commands: {e}")





bot.run(TOKEN, log_handler=handler, log_level=logging.DEBUG) 