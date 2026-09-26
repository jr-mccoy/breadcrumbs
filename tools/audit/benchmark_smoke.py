#!/usr/bin/env python3
"""Small deterministic timing probe, NOT a production performance benchmark.

Temporary no-git stores. Reports median/max of five in-process reads and one
reindex. This does not measure host hooks, cold Python startup, Windows, or model
latency. Run independently from correctness probes; never use timings as safety.
"""
from __future__ import annotations
import argparse, contextlib, io, json, os, platform, statistics, sys, tempfile, time
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,default=Path.cwd())
    ap.add_argument('--output',type=Path)
    ap.add_argument('--sizes',type=int,nargs='+',default=[100,500,501,1000])
    sys.dont_write_bytecode=True
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    args=ap.parse_args();sys.path.insert(0,str(args.source.resolve()))
    from breadcrumbs import cli, hooks_prompt, searchindex
    def measured(fn,n=5):
        values=[]
        for _ in range(n):
            t=time.perf_counter();value=fn();values.append((time.perf_counter()-t)*1000)
        return {'median_ms':round(statistics.median(values),2),'max_ms':round(max(values),2),'samples':n}
    rows=[]
    for size in args.sizes:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);mem=root/cli.MEMORY_DIRNAME
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                code=cli.main(['init','--project',str(root),'--session-tracking','full'])
                assert code==0
                p,m=cli.write_record(mem,root,'decision','Amber quasar routing policy',{'Decision':'Route quasar traffic through the amber queue.'},evidence=[{'type':'file','ref':'src/quasar.py'}])
                for i in range(1,size):
                    dest=mem/'decisions'/('2026-01-01-feature-%05d.md'%i)
                    meta=dict(m);meta['id'],meta['slug']=cli.derive_identity(dest.stem,'decision')
                    meta['title']='Feature %05d storage configuration'%i
                    meta['evidence']=[{'type':'file','ref':'src/feature_%05d.py'%i}]
                    dest.write_text(cli.render_frontmatter(meta)+'\n\n## Decision\nUse an explicit configuration for this feature.\n')
                index=searchindex.build_index(mem,root)
                row={'records':size,'index':index,'search':measured(lambda:cli.search(mem,root,'amber quasar routing')),
                     'prompt_retrieve':measured(lambda:hooks_prompt.retrieve(mem,root,'amber quasar routing')),
                     'prompt_hit_count':len(hooks_prompt.retrieve(mem,root,'amber quasar routing')),
                     'packet':measured(lambda:cli.build_resume_packet(mem,root),n=3),
                     'reindex':measured(lambda:cli.try_reindex_projections(mem),n=1)}
            rows.append(row);print(json.dumps(row),flush=True)
    report={'python':sys.version,'platform':platform.platform(),'scope':'synthetic no-git in-process smoke timings, not production SLO qualification','rows':rows}
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
