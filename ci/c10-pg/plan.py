"""C10 candidate-bound PostgreSQL before/after plan evidence runner."""
import argparse, hashlib, json, os, pathlib, time, uuid
import psycopg

QUERY="""SELECT j.journey_id,j.account_id,j.title,j.destination_summary,j.starts_at,j.created_at
FROM go_journey j
WHERE (j.account_id=%s OR EXISTS (
 SELECT 1 FROM consumer_trip_member m
 WHERE m.journey_id=j.journey_id AND m.user_id=%s AND m.status='ACTIVE'))
AND (lower(j.title) LIKE %s OR lower(coalesce(j.destination_summary,'')) LIKE %s)
ORDER BY j.starts_at ASC NULLS LAST,j.created_at ASC,j.journey_id ASC
OFFSET %s LIMIT %s"""
PARAMS=("owner-target","member-target","%target%","%target%",120,21)

def explain(cur):
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+QUERY,PARAMS)
    return cur.fetchone()[0][0]

def nodes(plan):
    result=[]
    def visit(node):
        result.append({
            "node_type":node.get("Node Type"),
            "index_name":node.get("Index Name"),
            "actual_rows":node.get("Actual Rows"),
            "actual_loops":node.get("Actual Loops"),
            "rows_removed_by_filter":node.get("Rows Removed by Filter"),
            "shared_hit_blocks":node.get("Shared Hit Blocks"),
            "shared_read_blocks":node.get("Shared Read Blocks"),
        })
        for child in node.get("Plans",[]): visit(child)
    visit(plan["Plan"])
    return result

def metrics(plan):
    root=plan["Plan"]; all_nodes=nodes(plan)
    return {
        "planning_ms":plan.get("Planning Time"),
        "execution_ms":plan.get("Execution Time"),
        "shared_hits":root.get("Shared Hit Blocks"),
        "shared_reads":root.get("Shared Read Blocks"),
        "node_types":[n["node_type"] for n in all_nodes],
        "indexes":[n["index_name"] for n in all_nodes if n["index_name"]],
        "journey_rows_removed":sum((n["rows_removed_by_filter"] or 0)*(n["actual_loops"] or 1) for n in all_nodes if n["node_type"] in ("Seq Scan","Bitmap Heap Scan")),
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--evidence-dir",required=True);a=ap.parse_args()
    out=pathlib.Path(a.evidence_dir);out.mkdir(parents=True,exist_ok=True)
    url=os.environ["GO_C10_RUNTIME_DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")
    schema="c10plan_"+uuid.uuid4().hex[:12];started=time.time()
    with psycopg.connect(url) as cx:
      with cx.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"');cur.execute(f'SET search_path TO "{schema}"')
        cur.execute("CREATE TABLE go_journey(journey_id text PRIMARY KEY,account_id text NOT NULL,title text NOT NULL,destination_summary text,starts_at timestamptz,created_at timestamptz NOT NULL)")
        cur.execute("CREATE TABLE consumer_trip_member(trip_member_id text PRIMARY KEY,journey_id text NOT NULL,user_id text NOT NULL,status text NOT NULL)")
        cur.execute("CREATE INDEX ix_journey_account_order ON go_journey(account_id,starts_at,created_at,journey_id)")
        cur.execute("CREATE INDEX ix_member_user_status_journey ON consumer_trip_member(user_id,status,journey_id)")
        cur.execute("""INSERT INTO go_journey
 SELECT 'j'||g, CASE WHEN g%40=0 THEN 'owner-target' ELSE 'owner-'||(g%200)::text END,
 CASE WHEN g%25=0 THEN 'Target Journey '||g ELSE 'Journey '||g END,
 CASE WHEN g%33=0 THEN 'target destination' ELSE 'destination '||(g%100)::text END,
 now()+(g||' minutes')::interval,now()-(g||' seconds')::interval
 FROM generate_series(1,20000) g""")
        cur.execute("""INSERT INTO consumer_trip_member
 SELECT 'm'||g,'j'||(g*20),'member-target','ACTIVE' FROM generate_series(1,500) g""")
        cur.execute("ANALYZE go_journey");cur.execute("ANALYZE consumer_trip_member")
        before=explain(cur)
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute("CREATE INDEX ix_go_journey_title_lower_trgm ON go_journey USING gin (lower(title) gin_trgm_ops)")
        cur.execute("CREATE INDEX ix_go_journey_destination_lower_trgm ON go_journey USING gin (lower(coalesce(destination_summary,'')) gin_trgm_ops)")
        cur.execute("ANALYZE go_journey")
        after=explain(cur)
        cur.execute(QUERY,PARAMS);rows=cur.fetchall()
        cur.execute("SELECT count(*) FROM go_journey");journeys=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM consumer_trip_member");members=cur.fetchone()[0]
        cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    bm,am=metrics(before),metrics(after)
    improvement=None
    if bm["execution_ms"]:
        improvement=round((bm["execution_ms"]-am["execution_ms"])/bm["execution_ms"]*100,3)
    raw={"task_id":"V70-R3-C10-PG-PLAN-FIX","source_commit":os.environ["GO_C10_SOURCE_COMMIT"],"application_tree":os.environ["GO_C10_APPLICATION_TREE"],"postgresql":"18.4","scale":{"journeys":journeys,"members":members},"query":QUERY,"parameters":PARAMS,"returned_rows":len(rows),"before":{"plan":before,"metrics":bm},"after":{"plan":after,"metrics":am},"execution_improvement_percent":improvement,"semantic_boundary":"same contains-search query and owner-or-active-member permission predicate; index-only candidate"}
    p=out/"explain_before_after.json";p.write_text(json.dumps(raw,indent=2,default=str)+"\n")
    sums={p.name:hashlib.sha256(p.read_bytes()).hexdigest()};(out/"SHA256SUMS.json").write_text(json.dumps(sums,indent=2)+"\n")
    print(json.dumps({"status":"EVIDENCE_READY","rows":len(rows),"before":bm,"after":am,"execution_improvement_percent":improvement,"sha256":sums[p.name]}))
if __name__=="__main__":main()
