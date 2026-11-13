"""Capture actual settings frames with simulated save storage, never a device."""
import copy,hashlib,json,sys
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'payload/opt/dino'))
from poker_app import PokerApp
from poker_training import TrainingState
from poker_training_store import TrainingStore


class DemoJournal:
    payload={};recovered=False
    def write(self,value):self.payload=copy.deepcopy(value)
    def close(self):pass


def main():
    out=ROOT/'validation/settings-v066';out.mkdir(exist_ok=True)
    store=TrainingStore(DemoJournal());app=PokerApp(training_state=TrainingState(store));frames={}
    def save(name):
        frame=app.render();frame.save(out/(name+'.png'))
        frame.resize((960,720),Image.Resampling.NEAREST).save(out/(name+'-3x.png'))
        frames[name]=hashlib.sha256((out/(name+'.png')).read_bytes()).hexdigest()
    try:
        app.settings.open();save('general-settings')
        app.settings.page='profiles';app.settings._select_profile_game(9);app.settings.profile_index=3
        save('paytable-presets');app.settings.page='pays';save('south-point-pays')
        app.settings.close();app.toggle_hidden_mode();app.trainer.page='settings';app.trainer.index=6
        save('memory-off');app.trainer.state.save();assert store.set_persistent(True);save('memory-on')
        app.trainer.page='clear_memory';app.trainer.index=0;save('clear-training-data')
        gallery=Image.new('RGB',(1280,1008),(5,7,30));draw=ImageDraw.Draw(gallery)
        for i,name in enumerate(('general-settings','paytable-presets','memory-off','memory-on')):
            x=(i%2)*640;y=(i//2)*504;draw.text((x+10,y+5),name.replace('-',' ').upper(),fill=(255,220,65))
            gallery.paste(Image.open(out/(name+'.png')).resize((640,480),Image.Resampling.NEAREST),(x,y+24))
        gallery.save(out/'settings-gallery.png')
        proof=json.loads((ROOT/'validation/artifact-readback-v066.json').read_text())
        for name,sha in proof['runtime_sha256'].items():assert hashlib.sha256((ROOT/'payload'/name).read_bytes()).hexdigest()==sha
        (out/'manifest.json').write_text(json.dumps({'version':'0.6.6','production_image_sha256':proof['image_sha256'],
            'fixture':'Actual production rendering with a simulated in-memory journal adapter; not physical photos',
            'screenshots':frames},indent=2)+'\n')
        print(json.dumps({'output':str(out),'frames':len(frames)}))
    finally:app.close()


if __name__=='__main__':main()
