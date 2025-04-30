import ollama
from time import time
# Generate embedding

emb = """#  52ViKING Emergency POS
![](https://help.fiftytwo.com/help/en-us/Content/Resources/Images/cog222.png) This topic is primarily for administrators and other people who manage a Fiftytwo solution
Retailers dread losing sales because it can threaten their business. One of the scenarios that retailers fear the most is being victims of a cyberattack.
![](https://help.fiftytwo.com/help/en-us/Content/Resources/Images/vign-epos-good-hacked-bad_1200x483.png)
With 52ViKING Emergency POS your stores can keep operating safely during cyberattacks and similar emergency situations so you don't lose sales.
52ViKING Emergency POS works on top of [52ViKING MPOS](https://help.fiftytwo.com/help/en-us/Content/_MO/admin/mo.htm). It backs up relevant master data from your stores' 52ViKING store controllers. At regular intervals it then uploads the backups to an isolated, secure Fiftytwo Emergency POS cloud repository from where isolated instances of your stores' mobile POSs, created when Emergency POS is activated, can reach your uncompromised data.
When you activate Emergency POS, you select a backup from a date on which you're sure that data wasn't compromised. That way, your stores can keep selling articles on mobile POS devices through secure 4G/5G connections to cloud-based mobile POSs that use data from the secure Emergency POS cloud repository that's unaffected by the emergency.
Isolating your Emergency POS from your daily operations prevents that an emergency that affects your regular POS system will affect your Emergency POS. Your Emergency POS will be available, reachable securely, and safe to use, so your stores can keep operating and sell articles during emergencies.
  * Individual stores can use their individual data: Because the Emergency POS solution backs up data from your individual stores' 52ViKING store controllers, Emergency POS lets your stores use their individual article data during emergencies, so they can allow for special local articles, local prices, campaigns,"""

models = ['nomic-embed-text', 'mxbai-embed-large', 'all-minilm', 'llama3.2']
for model in models:
    start_time = time()
    response = ollama.embeddings(model=model, prompt=emb)

    

    print(f"model {model}")
    
    
    print("----------------END-----------------")
    if model == "llama3.2":
        
        print("-------------------------")
        print(response['embedding'])
        
    print(F"Required Time {time() - start_time} \n__________________________________")   