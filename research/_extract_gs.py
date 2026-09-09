import re

md = open("SETUP_NOTIFICATIONS.md", encoding="utf-8").read()
js = re.search(r"```javascript\n(.*?)```", md, re.S).group(1)
open("nowcast_notifier.gs", "w", encoding="utf-8").write(js)
print("extracted", len(js), "chars")
