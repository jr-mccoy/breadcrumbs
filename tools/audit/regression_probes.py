#!/usr/bin/env python3
"""Read-only-of-source review probes for Breadcrumbs; all stores are temporary.

These characterize the reviewed version, not a replacement test suite. A true
`bug_observed` is a defect signal, not a test-suite success. Only temporary stores are mutated by the probes. No network calls, real secrets,
or destructive user commands are performed. Imported source must be trusted.
"""
from __future__ import annotations
import argparse, contextlib, io, json, os, platform, subprocess
import sys, tempfile, time, traceback
from pathlib import Path
from unittest import mock

ap=argparse.ArgumentParser()
ap.add_argument('--source', type=Path, default=Path.cwd())
ap.add_argument('--output', type=Path)
ap.add_argument('--fail-on-observed', action='store_true', help='exit 1 if any defect signal is observed (otherwise diagnostic exit 0); probe errors always exit 2')
args=ap.parse_args()
if not (args.source / 'breadcrumbs' / 'cli.py').is_file():
    ap.error('--source must identify a Breadcrumbs source checkout or source distribution')
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.path.insert(0,str(args.source.resolve()))
from breadcrumbs import cli, transcript as tr, hooks_prompt as hp, hooks_common as hc
from breadcrumbs import inbox, lifecycle, searchindex, promote, lock, mcp_core


def quiet(argv):
    out,err=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
        code=cli.main(argv)
    return code,out.getvalue(),err.getvalue()


def init(root):
    code,out,err=quiet(['init','--project',str(root),'--session-tracking','full'])
    if code: raise RuntimeError((code,out,err))
    return root/cli.MEMORY_DIRNAME


def call(cid='a', command='pytest'):
    return {'type':'assistant','message':{'content':[{'type':'tool_use','id':cid,'name':'Bash','input':{'command':command}}]}}


def result(cid='a', text='1 passed', is_error=False):
    return {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':cid,'content':text,'is_error':is_error}]}}


def correction(text):
    return {'type':'user','message':{'content':[{'type':'text','text':text}]}}


def record(mem,root,title='Amber quasar routing policy',status='active',scope=None):
    return cli.write_record(mem,root,'decision',title,{'Decision':'Route amber quasar traffic through the dedicated queue.'},evidence=[{'type':'file','ref':'src/quasar.py'}],status=status,scope=scope,agent='human')


def transcript_results():
    cases={
        'missing_result':[call()],
        'failure_after_400_chars':[call(),result(text='x'*450+'\nFAILED test_real_failure')],
        'zero_failed_success':[call(),result(text='15 passed, 0 failed')],
    }
    got={k:[c.title for c in tr.mine(v)[0]] for k,v in cases.items()}
    return {'bug_observed':bool(got['missing_result']) and bool(got['failure_after_400_chars']), 'candidates':got}


def sliding_cursor():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p=root/'transcript.jsonl'
        def line(text):
            obj=correction(text);obj['padding']='x'*500000
            return json.dumps(obj)+'\n'
        with p.open('w') as f:
            for i in range(18):f.write(line('ordinary progress '+str(i)))
        first=tr.read_transcript(p)
        r1=tr.mine_transcript_into_jots(mem,root,str(p),session_id='tail')
        before=hc.miner_cursor(mem,'tail')
        with p.open('a') as f:f.write(line('No, preserve the retry budget during deployment.'))
        last=tr.read_transcript(p)
        visible=bool(tr.mine(last)[0])
        r2=tr.mine_transcript_into_jots(mem,root,str(p),session_id='tail')
        return {'bug_observed':visible and not r2['written'],'first_tail_entries':len(first),'next_tail_entries':len(last),'stored_cursor':before,'candidate_exists_without_cursor':visible,'next_write_report':r2}


def split_pair():
    entries=[call('a','python -m pytest')]
    a,cursor=tr.mine(entries)
    entries.append(result('a','FAILED tests/test_x.py',True))
    b,_=tr.mine(entries,since_index=cursor)
    return {'bug_observed':bool(a) and not b,'first_firing_candidates':[c.title for c in a],'second_firing_candidates':[c.title for c in b]}


def prompt_cliff():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,meta=record(mem,root)
        for i in range(500):
            dest=mem/'decisions'/('2026-01-01-retired-entry-%04d.md'%i)
            m=dict(meta);m['id'],m['slug']=cli.derive_identity(dest.stem,'decision')
            m['title']='Retired record %04d'%i;m['status']='stale'
            dest.write_text(cli.render_frontmatter(m)+'\n\n## Decision\nOld unrelated history.\n')
        built=searchindex.build_index(mem,root)
        direct,_=cli.search(mem,root,'amber quasar routing',include_ideas=False)
        injected=hp.retrieve(mem,root,'amber quasar routing')
        return {'bug_observed':bool(direct) and not injected,'total_candidates':len(cli._candidate_items(mem)),'active_decisions':len(cli.active_decisions(mem)),'index':built,'search_ids':[m['id'] for m in direct[:5]],'hook_ids':[m['id'] for m in injected]}


def guard_prefilter():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root)
        note=cli.note(mem,root,'trap','npm test truncates the database',fields={'area':'package.json','symptom':'The integration test deletes persistent rows.','safe':'Use an isolated disposable database.'})
        assert note['ok'],note
        direct=cli.guard(mem,root,'npm test')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._hook_guard(mem,root,{'tool_name':'Bash','tool_input':{'command':'npm test'},'session_id':'prefilter'})
        hook=json.loads(out.getvalue())
        return {'bug_observed':direct['verdict']=='PROCEED','direct_verdict':direct['verdict'],'direct_ids':[m['id'] for m in direct['matches']],'hook_output':hook,'prefilter_hit':cli._prefilter_trap_hit(mem,'npm test',None),'scenario':'recorded test command destructively truncates a persistent database'}


def resume_ignores_lock():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p=mem/'generated'/'resume-packet.md'
        p.write_text('sentinel before resume\n')
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        lp=lock.lock_path(mem)
        try:
            lp.write_text('%d %.3f %s\n'%(child.pid,time.time(),lock._host()))
            code,out,err=quiet(['resume','--project',str(root),'--json'])
            changed=p.read_text()!='sentinel before resume\n'
            return {'bug_observed':code==0 and changed,'exit_code':code,'foreign_lock_remained':lp.exists(),'projection_changed':changed}
        finally:
            child.terminate();child.wait(timeout=5)
            lp.unlink(missing_ok=True)


def snapshot_stamp_race():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);real=cli._inputs_hash;created=[]
        def inject(*a,**kw):
            if not created:
                p,m=record(mem,root,'Newly added cerulean encryption policy');created.append(m['id'])
            return real(*a,**kw)
        with mock.patch.object(cli,'_inputs_hash',side_effect=inject):
            pkt=cli.build_resume_packet(mem,root)
        ids=[x['id'] for x in pkt['active_decisions']]
        stamp_matches=pkt['source']['inputs_hash']==real(mem,root)
        return {'bug_observed':stamp_matches and created[0] not in ids,'new_record':created[0],'packet_ids':ids,'stamp_matches_current_store':stamp_matches,'method':'deterministic interleaving between record read and input hashing'}


def recheck_scope_and_claim():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for argv in (['git','init','--quiet','--initial-branch=main'],['git','-c','user.name=Audit','-c','user.email=audit@example.invalid','commit','--quiet','--allow-empty','-m','audit baseline'],['git','checkout','--quiet','-b','feature/audit']):
            no_hooks=root/'_no_hooks'
            no_hooks.mkdir(exist_ok=True)
            argv=argv[:1]+['-c','core.hooksPath='+str(no_hooks),'-c','commit.gpgsign=false']+argv[1:]
            subprocess.run(argv,cwd=root,check=True,capture_output=True)
        mem=init(root)
        cmd='"%s" -c "pass"'%sys.executable
        v=cli.verify(mem,root,'Quasar authentication bug',status='open',scope='branch',evidence=[{'type':'command','ref':cmd}])
        assert v['ok'],v
        old=cli.find_record_by_id(mem,v['id'])
        got=lifecycle.recheck(mem,root,old)
        new=cli.find_record_by_id(mem,got['new_id'])
        subprocess.run(['git','checkout','--quiet','main'],cwd=root,check=True,capture_output=True)
        packet=cli.build_resume_packet(mem,root)
        return {'bug_observed':new.meta['scope']!='branch','old_scope':old.meta['scope'],'old_branch':old.meta['branch'],'new_scope':new.meta['scope'],'new_outcome':new.meta['outcome'],'reader_branch':cli.git_branch(root),'visible_on_other_branch':any(v['id']==new.meta['id'] for v in packet['verifications']),'command_was_only_noop':True}


def jot_promotion_loss():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);text='Invalidate both the tenant cache and the role cache before rotating the authorization epoch.'
        j=inbox.write_jot(mem,root,text,title='Cache invalidation finding',local=True,scope='branch',evidence=[{'type':'file','ref':'src/cache.py'}])
        assert j['ok'],j
        got=inbox.promote_jot(mem,root,j['id'],'decision')
        assert got['ok'],got
        rec=cli.find_record_by_id(mem,got['promoted_to'])
        raw=rec.path.read_text()
        return {'bug_observed':text not in raw,'original_text_in_promoted_record':text in raw,'new_scope':rec.meta['scope'],'new_confidence':rec.meta['confidence'],'new_record_body':rec.body.strip(),'jot_retired':inbox.find_jot(mem,j['id']).meta['status']}


def promoted_adapter_missing():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,m=record(mem,root)
        (root/'CLAUDE.md').write_text('# Agent guide\n')
        got=promote.promote(mem,root,m['id'],to='CLAUDE.md')
        assert got['ok'],got
        (root/'CLAUDE.md').unlink()
        packet=cli.build_resume_packet(mem,root)
        ids=[x['id'] for x in packet['active_decisions']]
        return {'bug_observed':m['id'] not in ids,'adapter_exists':(root/'CLAUDE.md').exists(),'active_decision_ids':ids,'promoted_counts':packet['promoted']}


def packet_bound():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root)
        (mem/'current.md').write_text('# Current State\n\n## Current Focus\n'+('Important context. '*1500)+'\n')
        packet=cli.build_resume_packet(mem,root)
        n=cli.approx_tokens(cli.render_packet_markdown(packet))
        return {'bug_observed':n>cli.TOKEN_BUDGET_MAX,'approx_tokens':n,'claimed_limit':cli.TOKEN_BUDGET_MAX}


def symlink_read():
    with tempfile.TemporaryDirectory() as td:
        base=Path(td);root=base/'project';root.mkdir();mem=init(root)
        external=base/'external-synthetic.txt';external.write_text('SYNTHETIC-OUTSIDE-STORE-CONTENT\n')
        (mem/'current.md').unlink();(mem/'current.md').symlink_to(external)
        got=mcp_core.resource_current(root)
        return {'bug_observed':'SYNTHETIC-OUTSIDE' in got,'mcp_resource_returned_external_bytes':got.strip(),'real_credentials_used':False}


def live_lock_stale():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root)
        with lock.store_lock(mem):
            now=time.time()
            with mock.patch.object(lock.time,'time',return_value=now+lock.STALE_SECONDS+5):
                stale=lock._is_stale(lock.lock_path(mem))
            return {'bug_observed':stale,'holder_is_current_live_process':True,'live_lock_classified_stale_after_heartbeat_gap':stale,'method':'injected wall-clock/heartbeat gap, not an OS-level stress test'}


def powershell_translation():
    action,files=cli._hook_action_from_tool('PowerShell',{'command':'Remove-Item ./cache -Recurse'})
    return {'bug_observed':not action,'registered_matcher':cli._HOOK_SPECS['guard'][1],'translated_action':action}

def schema_types():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,m=record(mem,root)
        cases={}
        for field,value in [('confidence','certainly'),('scope','all-machines'),('evidence',[{'nonsense':'not evidence'}]),('expires_at',12345),('superseded_by','dec_missing')]:
            meta=dict(m);meta[field]=value
            if field=='superseded_by':meta['status']='superseded'
            p.write_text(cli.render_frontmatter(meta)+'\n\n## Decision\nRoute amber quasar traffic through the dedicated queue.\n')
            try:
                # Validate the actual record, not unrelated projection freshness.
                record_fails=cli._validate_new_file(mem,p)
                validation={'record_validation_failed':bool(record_fails),'findings':record_fails}
            except Exception as exc:validation={'validation_error':type(exc).__name__+': '+str(exc)}
            try:
                cli.build_resume_packet(mem,root)
                runtime='returned'
            except Exception as exc:runtime=type(exc).__name__+': '+str(exc)
            cases[field]={**validation,'packet':runtime}
        return {'bug_observed':any(not x.get('record_validation_failed',True) for x in cases.values()),'cases':cases}


def short_prompt_and_stale_task():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,m=record(mem,root,'Quasar policy')
        cli.reindex_projections(mem)
        short='quasar'
        direct=hp.retrieve(mem,root,short)
        actual=hp.hook_prompt(mem,root,{'prompt':short,'session_id':'short'})
        hp.hook_prompt(mem,root,{'prompt':'amber quasar routing policy','session_id':'switch'})
        hp.hook_prompt(mem,root,{'prompt':'Design a completely unrelated calendar view','session_id':'switch'})
        saved=hc.prompt_state(mem,'switch').get('last_prompt')
        return {'bug_observed':bool(direct) and not actual,'direct_ids':[x['id'] for x in direct],'short_prompt_output':actual,'remembered_prompt_after_unrelated_task':saved,'actual_latest_prompt':'Design a completely unrelated calendar view'}


def index_metadata_collision():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,m=record(mem,root)
        for i in range(200):
            dest=mem/'decisions'/('2026-01-01-other-entry-%04d.md'%i)
            meta=dict(m);meta['id'],meta['slug']=cli.derive_identity(dest.stem,'decision')
            meta['title']='Different record %04d'%i
            dest.write_text(cli.render_frontmatter(meta)+'\n\n## Decision\nUnrelated ordinary record.\n')
        built=searchindex.build_index(mem,root)
        st=p.stat();original=p.read_text()
        p.write_text(original.replace('Route amber quasar traffic','Route amber nebula traffic'))
        os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        assert p.stat().st_size == st.st_size
        assert not cli._validate_new_file(mem,p)
        state=searchindex.index_status(mem,root)
        indexed,_=cli.search(mem,root,'nebula',include_ideas=False)
        with mock.patch.object(searchindex,'candidate_items',return_value=None):
            full,_=cli.search(mem,root,'nebula',include_ideas=False)
        return {'bug_observed':bool(full) and not indexed,'index':built,'reported_state':state,'indexed_ids':[x['id'] for x in indexed],'full_scan_ids':[x['id'] for x in full],'same_size_and_restored_mtime':True}


def guard_usage_dedupe():
    from breadcrumbs import usage
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,m=record(mem,root)
        cli.reindex_projections(mem)
        payload={'tool_name':'Edit','tool_input':{'file_path':'src/quasar.py','new_string':'refactor amber quasar routing policy'},'session_id':'counts'}
        outputs=[]
        for _ in range(2):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):cli._hook_guard(mem,root,payload)
            outputs.append(json.loads(out.getvalue()))
        counts=usage.load_usage(mem)['records'].get(m['id'])
        return {'bug_observed':bool(outputs[0]) and not outputs[1] and counts is not None,'first_spoke':bool(outputs[0]),'second_spoke':bool(outputs[1]),'usage':counts}


def partial_supersession():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);mem=init(root);p,m=record(mem,root)
        # Controlled failure in the real return-value protocol: no disk damage.
        with mock.patch.object(cli,'set_record_status',return_value={'ok':False,'error':'synthetic retirement failure'}):
            code,out,err=quiet(['remember','decision','--project',str(root),'--title','Replace quasar queue policy','--set','Decision','Route quasar traffic through a revised queue.','--evidence','file','src/quasar.py','--supersedes',m['id'],'--json'])
        old=cli.find_record_by_id(mem,m['id'])
        live=[r.meta['id'] for r in cli.load_records(mem,types=['decision']) if r.meta['status']=='active']
        return {'bug_observed':code==0 and old.meta['status']=='active' and len(live)==2,'command_exit':code,'old_status':old.meta['status'],'live_decisions':live,'method':'injected failure return during retirement; new record really written'}


PROBES=[transcript_results,sliding_cursor,split_pair,prompt_cliff,guard_prefilter,resume_ignores_lock,snapshot_stamp_race,recheck_scope_and_claim,jot_promotion_loss,promoted_adapter_missing,packet_bound,symlink_read,live_lock_stale,powershell_translation,schema_types,short_prompt_and_stale_task,index_metadata_collision,guard_usage_dedupe,partial_supersession]
report={'reviewed_commit':'30e41f6a36195faffdc197d0565abc7caf7c78da','source':str(args.source.resolve()),'python':sys.version,'platform':platform.platform(),'probes':{}}
for probe in PROBES:
    start=time.perf_counter()
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            value=probe()
    except Exception as exc:
        value={'probe_error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()}
    value['seconds']=round(time.perf_counter()-start,4)
    report['probes'][probe.__name__]=value
    print(probe.__name__,json.dumps(value,ensure_ascii=True),flush=True)
if args.output:
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=True)+'\n')
print('Probes:',len(report['probes']),'defect signals:',sum(x.get('bug_observed',False) for x in report['probes'].values()),'probe errors:',sum('probe_error' in x for x in report['probes'].values()))

errors=sum("probe_error" in x for x in report["probes"].values())
observed=sum(bool(x.get("bug_observed")) for x in report["probes"].values())
raise SystemExit(2 if errors else (1 if args.fail_on_observed and observed else 0))
