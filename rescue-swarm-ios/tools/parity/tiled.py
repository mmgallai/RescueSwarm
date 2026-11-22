"""Frozen D85 overlapping-crop comparison. No calibration, fitting or app edits."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import compare


def rectangles(w, h):
    dx, dy = round(w / 4 * .1), round(h / 4 * .1)
    return [(max(0, i*w//4-dx), max(0, j*h//4-dy),
             min(w, (i+1)*w//4+dx), min(h, (j+1)*h//4+dy))
            for j in range(4) for i in range(4)]


def prepare(root):
    from PIL import Image
    compare.provision(root)
    manifest = json.loads((root/'manifest.json').read_text())
    (root/'source-manifest.json').write_text(json.dumps(manifest, indent=2))
    cropped = copy.deepcopy(manifest)
    cropped['crop_fixture'] = True
    cropped['images'] = []
    for row in manifest['images']:
        with Image.open(root/row['path']) as im:
            im = im.convert('RGB')
            assert im.size == (row['width'], row['height'])
            for index, rect in enumerate(rectangles(*im.size)):
                ident = row['id'] + f'-crop{index:02}'
                path = root/(ident+'.png')
                im.crop(rect).save(path)
                cropped['images'].append(dict(id=ident, source_id=row['id'], rect=rect,
                    path=path.name, width=rect[2]-rect[0], height=rect[3]-rect[1], boxes=[],
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert len(cropped['images']) == 512
    (root/'manifest.json').write_text(json.dumps(cropped, indent=2))


def nms(ds):
    kept = []
    for d in sorted(ds, key=lambda d: -d['confidence']):
        if all(compare.iou(d['box'], k['box']) <= .5 for k in kept):
            kept.append(d)
    return kept


def run(root):
    compare.run(root)
    crops = json.loads((root/'manifest.json').read_text())
    source = json.loads((root/'source-manifest.json').read_text())
    patch_results = json.loads((root/'paired-results.json').read_text())
    (root/'crop-results.json').write_text(json.dumps(patch_results, indent=2))
    lookup = {r['id']: r for r in crops['images']}
    modes = ['swift', 'python_native', 'python_swift_pixels', 'python_pytorch']
    groups = {r['id']: {m: [] for m in modes} for r in source['images']}
    for r in patch_results['images']:
        tile = lookup[r['id']]
        x, y = tile['rect'][:2]
        for mode in modes:
            for d in r[mode]['detections']:
                b = d['box']
                groups[tile['source_id']][mode].append(dict(box=[b[0]+x,b[1]+y,b[2]+x,b[3]+y], confidence=d['confidence']))
    rows = [dict(id=ident, **{m: dict(detections=nms(ds)) for m,ds in modeset.items()}) for ident,modeset in groups.items()]
    swift = {r['id']: r['detections'] for r in json.loads((root/'swift-merged.json').read_text())['images']}
    for r in rows:
        # Independent Swift restoration and suppression must exactly match Python's.
        assert r['swift']['detections'] == swift[r['id']], r['id']
    (root/'crop-manifest.json').write_text(json.dumps(crops, indent=2))
    (root/'manifest.json').write_text(json.dumps(source, indent=2))
    (root/'paired-results.json').write_text(json.dumps(dict(images=rows, environment=patch_results['environment']), indent=2))
    compare.audit(root)
    report = json.loads((root/'comparison.json').read_text())
    # Also reproduce historical confidence-ordered matching, without threshold selection.
    truth = {r['id']: r['boxes'] for r in source['images']}
    report['historical_greedy_accuracy'] = {}
    for mode in modes:
        tp = fp = 0
        for r in rows:
            used = set()
            for d in sorted(r[mode]['detections'], key=lambda d:-d['confidence']):
                score, j = max(((compare.iou(d['box'], b), j) for j,b in enumerate(truth[r['id']]) if j not in used), default=(0,-1))
                if score >= .5:
                    tp += 1; used.add(j)
                else:
                    fp += 1
        total = sum(map(len,truth.values()))
        report['historical_greedy_accuracy'][mode] = dict(tp=tp,fp=fp,fn=total-tp, recall=tp/total,precision=tp/max(1,tp+fp))
    report['swift_global_merge_check'] = 'PASS'
    report['limitations'] += ['Lossless crop fixtures use the historical PIL decoding and exact integer grid. Swift independently restores coordinates and performs global NMS.',
        'Original research used GB10 FP16 batches of 16; this macOS PyTorch reference is CPU FP32 and sequential. No timing equivalence claimed.',
        '32 reused validation images, not the historical full 247-image cohort. No recalibration.']
    (root/'comparison.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    root = Path(os.environ['PARITY_ROOT'])
    {'prepare': prepare, 'run': run}[sys.argv[1]](root)
