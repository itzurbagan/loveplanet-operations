"""Prepare local configuration and pair the extension without printing credentials."""
import argparse,getpass,json,os,secrets,shutil
from pathlib import Path
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--data-dir',type=Path,default=root/'data')
p.add_argument('--openrouter-key',action='store_true',help='Ask for key without echoing it')
args=p.parse_args()
if not (root/'config.json').exists():shutil.copy2(root/'config.example.json',root/'config.json')
args.data_dir.mkdir(parents=True,exist_ok=True);os.chmod(args.data_dir,0o700)
key=args.data_dir/'bridge.key'
if not key.exists():key.write_text(secrets.token_urlsafe(32))
os.chmod(key,0o600)
bridge=root/'extension/bridge-config.json'
bridge.write_text(json.dumps({'key':key.read_text().strip()}));os.chmod(bridge,0o600)
if args.openrouter_key:
 value=getpass.getpass('OpenRouter API key: ').strip()
 if not value:raise SystemExit('Empty key; nothing saved')
 target=args.data_dir/'openrouter.key';target.write_text(value);os.chmod(target,0o600)
print('Configuration ready. Edit config.json and the profile mapping in extension/content.js before enabling replies.')
