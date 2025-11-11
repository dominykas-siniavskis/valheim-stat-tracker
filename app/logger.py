from colorama import init as color_init, Fore, Style
color_init(autoreset=True)

def ok(msg): print(f"{Fore.GREEN}✔ {msg}{Style.RESET_ALL}")
def info(msg):  print(f"{Fore.CYAN}▶ {msg}{Style.RESET_ALL}")
def warning(msg):  print(f"{Fore.YELLOW}⚠ {msg}{Style.RESET_ALL}")
def error(msg):   print(f"{Fore.RED}✖ {msg}{Style.RESET_ALL}")