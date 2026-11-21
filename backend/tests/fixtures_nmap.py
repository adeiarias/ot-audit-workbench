NMAP_XML = """<?xml version="1.0"?>
<nmaprun>
 <host><status state="up"/>
  <address addr="10.0.0.5" addrtype="ipv4"/>
  <address addr="00:1D:9C:AA:BB:CC" addrtype="mac" vendor="Rockwell"/>
  <hostnames><hostname name="plc1.local"/></hostnames>
  <ports>
   <port protocol="tcp" portid="502"><state state="open"/><service name="mbap" product="" version=""/></port>
   <port protocol="tcp" portid="80"><state state="open"/><service name="http" product="nginx" version="1.2"/></port>
   <port protocol="tcp" portid="23"><state state="closed"/></port>
  </ports>
 </host>
 <host><status state="down"/><address addr="10.0.0.9" addrtype="ipv4"/></host>
</nmaprun>"""
