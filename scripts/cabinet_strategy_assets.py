"""Non-executing, pinned inventory for the twelve certified cabinet policies."""
import hashlib
import json

CABINET_FILES = {'opt/dino/strategy/cabinet/bp10.json': '38e0e747e2bd95f254a3aa2638f55bbe892a2c26ff472c55a03871f9fd3a91b1', 'opt/dino/strategy/cabinet/bp3.json': 'fe6cac06901cf4935921e34d2eadb3347c3db21b4686969f0ab1fff179083fe3', 'opt/dino/strategy/cabinet/bpd3.json': 'b6bf4aeb756e6fcf1b79f6934f895588c9363c79f1ff1b208d4ae78d762a4109', 'opt/dino/strategy/cabinet/db5.json': '5fbc32f408320d0162e80ff234d6c3ad59343739fd43c47740ce50c46b8f0cb2', 'opt/dino/strategy/cabinet/ddb10.json': '194742adca9f9fcd8430ba07a4f3d78d2668f92b02887799e027d1777ab7cfda', 'opt/dino/strategy/cabinet/ddb10_75.json': '5d28b8c63b4ebd0e77f2ad72743566b3581969eaddfbda8e52c63e58a468af41', 'opt/dino/strategy/cabinet/ddb10_85.json': '37192584734cac5f6a86914ab2c28a925d11d145158aae3a0161cc539292a57d', 'opt/dino/strategy/cabinet/ddb10_95.json': '3685b05a2e813a5fc46e8f23b60d0c24f831d5461b4a3fc627588ad9c5097f52', 'opt/dino/strategy/cabinet/ddb3.json': '8d594e3b68d95f0080ed4665e202c94ba17da74be9b01d4a2132d85d6315b74c', 'opt/dino/strategy/cabinet/ddb3_75.json': '254c0cfd05d3f691fb4fc8f2dce1fb7d9f59736515f5135f5a99aa6390dcbfda', 'opt/dino/strategy/cabinet/ddb3_85.json': 'a99619c9e28c5d7610f48b1224faebc942325852f4cf0aa755b3c37b4bf13e0e', 'opt/dino/strategy/cabinet/ddb3_95.json': '18bd3b855c20b3738b7b5011319ab8e58b663f343aaa5b5aa2fe02412e5434a6', 'opt/dino/strategy/cabinet/dw3.json': '90ae8a91bb6c2132cb0e45b5c08da2fb5f2170bb7d33807402125d81b631a0eb', 'opt/dino/strategy/cabinet/dw5.json': '6c8f47687a161b26e13469fc3c9d0a2759e374a2b9583688205253868b74fb56', 'opt/dino/strategy/cabinet/dwb10.json': 'c84c529052c4232e1ed2f105008438ab44eb72d7febede68c7f2344ba0a5523a', 'opt/dino/strategy/cabinet/job5.json': '6fdac750328bd585d791d35155189b48f876ddb0c6478769a6641434d09d30c8', 'opt/dino/strategy/cabinet/joker5.json': 'c7381a783cd9fc128ec7d02ac1ebf5edca53dfa93e5551e9e4a96fdb6dbf5988', 'opt/dino/strategy/cabinet/tdb10.json': '2bef4b8b2f6963730a1ab2e6ee4a038703860d44dea4a1abc3b1545d98887a46', 'opt/dino/strategy/deuces_counts.dat': 'cd6d00050613efe751b63f28f6073bdedf2e32abb236fe4b5259fac6dab98cda', 'opt/dino/strategy/joker_counts.dat': 'ce149b8d3d55df49f91197cfea6bd85da1aebac430f4d938d615fec6e6f8412a'}

def validate_cabinet_inventory(files):
    present=set(files)&set(CABINET_FILES)
    if not present and 'opt/dino/poker_games.py' not in files:return None
    required={'opt/dino/poker_games.py','opt/dino/poker_evaluate.py','opt/dino/poker_cabinet_strategy.py','opt/dino/poker_cabinet_ui.py'}
    if not required <= set(files):raise ValueError('Missing cabinet application source')
    for name,digest in CABINET_FILES.items():
        body=files.get(name)
        if body is None or len(body)>8*1024*1024 or hashlib.sha256(body).hexdigest()!=digest:
            raise ValueError('Missing or changed certified cabinet resource: '+name)
        if name.endswith('.json'):
            meta=json.loads(body)
            if meta.get('schema')!=2 or meta.get('game_id')!=name.rsplit('/',1)[1][:-5]:raise ValueError('Invalid cabinet policy identity')
    return {'status':'PASS','game_count':12,'policy_count':18,'resource_count':len(CABINET_FILES),'resources_sha256':CABINET_FILES}
