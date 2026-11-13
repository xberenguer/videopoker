#!/usr/bin/env python3
"""Package corresponding source only after source, image and evidence agree."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_poker_image import PROJECT_VERSION,collect_payload
VERSION=PROJECT_VERSION
PREFIX='videopoker-v'+VERSION


def digest(body):return hashlib.sha256(body).hexdigest()


def main():
    records=collect_payload(ROOT/'payload')
    runtime={name:digest(body) for name,(mode,body) in records.items() if stat.S_ISREG(mode)}
    tag='v'+VERSION.replace('.','')
    image=ROOT/'outputs'/('videopoker-v'+VERSION+'-pi0-320x240.img')
    image_sha=digest(image.read_bytes())
    tests=json.loads((ROOT/'validation/tests.json').read_text())
    if (tests.get('status')!='PASS' or tests.get('version')!=VERSION
            or tests.get('payload_files_sha256')!=runtime or not tests.get('wall_clock_input_qualified')):
        raise ValueError('Current full host checks are missing or stale')
    files=[]
    for directory in ('payload','scripts','tests','native','docs'):
        for path in (ROOT/directory).rglob('*'):
            if path.is_symlink():raise ValueError('Source symlink: '+str(path))
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo') and not path.name.startswith('.'):
                files.append(path)
    for name in ('README.md','LICENSE','NOTICE','CHANGELOG.md','requirements-dev.txt','.gitignore'):
        path=ROOT/name
        if path.is_file():files.append(path)
    for name in ('seedsigner-pgp.asc','seedsigner.0.8.7.sha256.txt','seedsigner.0.8.7.sha256.txt.sig'):
        files.append(ROOT/'inputs'/name)
    for name in ('tests.json','full-flow.json','input-latency.json','artifact-readback-'+tag+'.json','release-validation-'+tag+'.json'):
        files.append(ROOT/'validation'/name)
    for folder in ('arm-training-'+tag,'arm-regression-'+tag):
        base=ROOT/'validation'/folder
        report=json.loads((base/'arm-report.json').read_text())
        if report.get('status')!='PASS' or report.get('version')!=VERSION or report.get('production_image_sha256')!=image_sha:
            raise ValueError('Native evidence is missing or stale: '+folder)
        files.append(base/'arm-report.json')
        for name,sha in report.get('png_sha256',{}).items():
            if Path(name).name!=name or not name.endswith('.png'):raise ValueError('Unsafe native screenshot')
            path=base/name
            if digest(path.read_bytes())!=sha:raise ValueError('Native screenshot differs: '+name)
            files.append(path)
    gallery=ROOT/'validation'/('live-training-'+tag)
    capture=json.loads((gallery/'manifest.json').read_text())
    if capture.get('version')!=VERSION or capture.get('payload_sha256')!=runtime:
        raise ValueError('Live screenshots do not match the runtime')
    files.append(gallery/'manifest.json')
    for screen in capture['screens']:
        name=screen['name']
        if Path(name).name!=name:raise ValueError('Unsafe capture name')
        path=gallery/(name+'.png')
        if digest(path.read_bytes())!=screen['frame_sha256']:raise ValueError('Capture changed: '+name)
        files.append(path)
    tour=ROOT/'validation'/('feature-tour-'+tag)
    if (tour/'manifest.json').is_file():
        detail=json.loads((tour/'manifest.json').read_text())
        if detail.get('version')!=VERSION or detail.get('production_image_sha256')!=image_sha:
            raise ValueError('Feature tour belongs to another image')
        files.extend((tour/'manifest.json',tour/'render.py'))
        for name,sha in detail['screenshots'].items():
            if Path(name).name!=name:raise ValueError('Unsafe feature capture')
            path=tour/(name+'.png')
            if digest(path.read_bytes())!=sha:raise ValueError('Feature capture changed: '+name)
            files.append(path)
    settings=ROOT/'validation'/('settings-'+tag)
    if (settings/'manifest.json').is_file():
        detail=json.loads((settings/'manifest.json').read_text())
        if detail.get('version')!=VERSION or detail.get('production_image_sha256')!=image_sha:
            raise ValueError('Settings captures belong to another image')
        files.append(settings/'manifest.json')
        for name,sha in detail['screenshots'].items():
            if Path(name).name!=name:raise ValueError('Unsafe settings capture')
            path=settings/(name+'.png')
            if digest(path.read_bytes())!=sha:raise ValueError('Settings capture changed: '+name)
            files.append(path)
    files=sorted(set(files),key=lambda p:p.relative_to(ROOT).as_posix())
    hashes={};bodies={}
    for path in files:
        name=path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in ('.img','.gba','.gb','.gbc','.nes','.so','.bin','.zip'):
            raise ValueError('Unexpected binary/ROM: '+name)
        body=path.read_bytes()
        if name.startswith('validation/') and path.suffix=='.json':
            body=body.replace(str(ROOT).encode(),b'.')
        bodies[name]=body;hashes[name]=digest(body)
    inventory={'schema':1,'version':VERSION,'production_image_sha256':image_sha,
               'public_validation_paths_normalized':True,'files_sha256':hashes}
    bodies['SOURCE-INVENTORY.json']=(json.dumps(inventory,indent=2)+'\n').encode()
    buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',filename='',mtime=0,compresslevel=9) as stream:
        with tarfile.open(fileobj=stream,mode='w',format=tarfile.PAX_FORMAT) as archive:
            for name,body in sorted(bodies.items()):
                entry=tarfile.TarInfo(PREFIX+'/'+name)
                entry.size=len(body);entry.mode=0o644;entry.mtime=1672531200
                entry.uid=entry.gid=0;entry.uname=entry.gname=''
                archive.addfile(entry,io.BytesIO(body))
    output=ROOT/'outputs'/(PREFIX+'-source.tar.gz')
    if output.exists():raise ValueError('Refusing to overwrite a source archive')
    output.write_bytes(buffer.getvalue());sha=digest(buffer.getvalue())
    output.with_name(output.name+'.sha256').write_text(sha+'  '+output.name+'\n')
    with tarfile.open(output,'r:gz') as archive:
        members=archive.getmembers()
        if len(members)!=len(bodies):raise ValueError('Archive member count differs')
        for member in members:
            name=member.name.removeprefix(PREFIX+'/')
            if not member.isfile() or archive.extractfile(member).read()!=bodies[name]:
                raise ValueError('Archive readback differs: '+name)
    report={'schema':1,'version':VERSION,'archive':str(output),'sha256':sha,
            'production_image_sha256':image_sha,'files_verified':len(bodies),
            'every_member_read_back':True,'files_sha256':hashes,'base_image_included':False,
            'public_validation_paths_normalized':True,
            'physical_hardware_tested':False,'github_published':False}
    (ROOT/'validation'/('source-verification-'+tag+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='files_sha256'},indent=2))


if __name__=='__main__':main()
