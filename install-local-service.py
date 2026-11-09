#!/usr/bin/env python3
"""Install user-owned launchd service. No passwords or Google credentials are stored."""
from pathlib import Path
import plistlib,subprocess,sys,os,shutil
source=Path(__file__).resolve().parent
root=Path.home()/'Library/Application Support/LovePlanet Operations'
root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o700)
for name in ('server.py','live_agent.py','model_provider.py','config.json','prompt.md'):
    shutil.copy2(source/name,root/name)
shutil.copytree(source/'dist',root/'dist',dirs_exist_ok=True)
(root/'data').mkdir(exist_ok=True);os.chmod(root/'data',0o700)

agent=Path.home()/'Library/LaunchAgents/ru.loveplanet.dialogops.plist'
agent.parent.mkdir(parents=True,exist_ok=True)
content={'Label':'ru.loveplanet.dialogops','ProgramArguments':['/usr/bin/caffeinate','-i',sys.executable,str(root/'server.py')],'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'StandardOutPath':str(root/'data/service.log'),'StandardErrorPath':str(root/'data/service-error.log'),'EnvironmentVariables':{'PYTHONUNBUFFERED':'1','TRANSPORT_MODE':'disabled'}}
agent.write_bytes(plistlib.dumps(content));os.chmod(agent,0o600)
domain='gui/'+str(os.getuid());name=domain+'/ru.loveplanet.dialogops'
loaded=subprocess.run(['launchctl','print',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
if loaded:subprocess.run(['launchctl','kickstart','-k',name],check=True)
else:subprocess.run(['launchctl','bootstrap',domain,str(agent)],check=True)
print('Service installed: ru.loveplanet.dialogops')
