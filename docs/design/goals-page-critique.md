Query: You are a senior staff engineer reviewing a design doc before 
implementation. Be direct, specific, and short. No praise padding.

The design doc is in the file 
/Users/engineer/.hermes/cache/scratch/goals-plugin-design.md (read it first with
read_file). Context you may verify in the installed Hermes tree at 
/Users/engineer/.hermes/hermes-agent: hermes_cli/goals.py (GoalState, state_meta
key goal:<sid>), hermes_cli/heartbeat.py, plugins/hermes-achievements/dashboard 
(manifest + plugin_api.py example), apps/desktop/src/store/goals.ts, 
website/docs/developer-guide/desktop-plugin-sdk.md. Real data lives in 
~/.hermes/state.db and ~/.hermes/profiles/*/state.db (read-only please; sqlite3 
is available).

Deliver, in markdown, under 900 words:
1. Blocking issues: anything that makes the design wrong, unsafe, or unshippable
(concurrency on live SQLite files, wrong assumptions about the plugin APIs, data
that doesn't exist where the doc says).
2. Answers to the 4 open questions at the end of the doc, each with a one-line 
recommendation.
3. Cuts: what to remove from v1 to ship in one day.
4. The 3 tests you would insist on.
Verify claims against the code where you can; say "verified" or "not verified" 
per claim you lean on.

 ─  ☤ Hermes  ───────────────────────────────────────────────────────────────── 
                                                                                
 Verdict: SHIP WITH CHANGES                                                     
                                                                                
 Ship a current-goals viewer, not a reconstructed goal-history system. The      
 proposed history, completion grouping, and cross-profile navigation are not    
 correct as written.                                                            
 1. Blocking issues                                                             
 1. “Cleared” does not mean completed                                           
                                                                                
 Verified: hermes_cli/goals.py:675–705 marks the old goal cleared when          
 compression copies it to a child session. Manual clearing also produces        
 cleared without completion (1225–1230).                                        
                                                                                
 The proposed Completed section would show abandoned goals and compression      
 copies as successes. A read-only inspection found a cleared row in             
 product-lead-agentpod/state.db.                                                
                                                                                
 Fix: Only done means completed. Exclude cleared rows from completion counts    
 and resolve compression lineage.                                               
 2. The promised history does not exist reliably                                
                                                                                
 Verified: GoalManager.set() replaces the session’s goal state                  
 (goals.py:1173–1182); persistence overwrites the same goal:<sid> key           
 (661–670). Automatic post-turn judging updates last_verdict and last_reason    
 directly—not through goal(complete) (1521–1526). GoalState has no              
 completed_at, and mark_done() does not record one (1232–1238).                 
                                                                                
 Consequently, scanning completion-tool calls cannot recover every verdict,     
 messages from earlier goals can contaminate the current goal’s Activity, and   
 “Completed in the last seven days” lacks a dependable timestamp. Slash-created 
 goals also need not have a goal(create) tool call.                             
                                                                                
 Fix: Show current state and “latest recorded judge result.” Drop complete      
 Activity and seven-day completion claims. A transcript excerpt is not a goal   
 event log.                                                                     
 3. Backend placement and navigation conflict with the SDK                      
                                                                                
 Verified: apps/desktop/src/api/plugins.ts:72–86 sends ctx.rest through the     
 active profile’s API scope. Installing the backend only in default does not    
 establish routing to default from every other profile.                         
                                                                                
 Verified: The SDK provides host.openSession(id, { profile }) specifically for  
 profile-aware session opening (desktop-plugin-sdk.md:917–920).                 
 host.navigate('/chat/<sid>') does not express the owning profile.              
                                                                                
 Fix: Specify and test the backend routing topology. Use profile-aware session  
 opening; key cached results by connection and profile. Show an explicit        
 unavailable state when the connected backend lacks the plugin.                 
                                                                                
 Also, backend presence alone does not enable it: plugins.enabled is required   
 (desktop-plugin-sdk.md:1370–1376).                                             
 4. “Tracking” would hide failures; “Needs you” overstates certainty            
                                                                                
 Verified: paused_reason includes judge transport failures, parsing failures    
 and exhausted turn budgets (goals.py:1562–1581). Those are not healthy         
 background tracking. blocked also means impossible or out-of-scope work, not   
 necessarily a user decision (131–144).                                         
                                                                                
 Verified: resume() leaves the previous verdict intact (1215–1223), so          
 classifying from last_verdict == "blocked" alone can retain an obsolete        
 warning.                                                                       
                                                                                
 Not verified: The proposed matcher correctly identifies the Neon and Gemma     
 cases. Badge-count equality only proves arithmetic consistency, not            
 classification accuracy.                                                       
                                                                                
 Fix: Use Active / Waiting / Paused / Done. If retaining text inference, label  
 it “May need attention,” suppress terminal and superseded signals, and show    
 the evidence.                                                                  
 5. Read-only SQLite is appropriate, but the failure contract is missing        
                                                                                
 Verified: Hermes already supports cross-profile read-only connections,         
 including bounded retries for transient WAL I/O errors                         
 (hermes_state.py:689–731). Achievements uses SessionDB(read_only=True) and     
 closes it (plugin_api.py:557–615).                                             
                                                                                
 Not verified: The proposed endpoint meets 300 ms or remains responsive during  
 checkpoints and profile replacement.                                           
                                                                                
 Fix: Use the existing read-only path with explicit DB paths, short reads,      
 guaranteed closure and off-event-loop execution. Return per-profile errors and 
 freshness—not an apparently complete empty list. PRAGMA query_only alone does  
 not prove the connection was opened read-only.                                 
                                                                                
 Cross-profile aggregation also needs an explicit authorized profile allowlist; 
 filesystem readability is not endpoint authorization. Actual exposure through  
 the deployed authentication setup is not verified.                             
 2. Answers to the four questions                                               
                                                                                
 1. Tracking/Goals: Do not wait for upstream kind; ship factual status groups   
 instead of inferring intent.                                                   
 2. Two frontends: Ship the dashboard first because it reaches the phone; defer 
 the separate desktop frontend.                                                 
 3. Activity: Show current state plus a session link now; add structured        
 append-only events later if reliable history becomes necessary.                
 4. SQLite aggregation: Use one authorized local read-only aggregator;          
 per-gateway fan-out adds availability and routing dependencies without fixing  
 data semantics.                                                                
 3. Cuts for a one-day v1                                                       
                                                                                
 - Desktop frontend, dynamic sidebar badge and dual-SDK component sharing.      
 - Tracking/Goals inference and definitive “Needs you” classification.          
 - Reconstructed judge history, artifact regex extraction and                   
 supervisor-message parsing.                                                    
 - Seven-day completion filtering.                                              
 - Message-body scans during list polling.                                      
                                                                                
 Keep profile filtering, objective, full contract, subgoals, gate status,       
 current status, latest reason, freshness and session navigation. Verified:     
 subgoals and gates are part of GoalState (goals.py:436–454); omitting them     
 would hide completion requirements.                                            
 4. Three required tests                                                        
                                                                                
 1. State semantics: Exercise replacement, pause/resume and compression         
 migration; cleared copies never count as completed, and old blockers do not    
 survive as current attention signals.                                          
 2. SQLite resilience: On disposable WAL databases, run writes/checkpoints      
 alongside polling; verify write rejection, bounded latency, connection cleanup 
 and visible partial failure when one profile breaks.                           
 3. Real UI routing: Load the chosen frontend through its actual backend mount; 
 compare rows with read-only SQL, switch profiles, open the correct owning      
 session, and verify missing-backend/auth failures cannot display stale data as 
 current.                                                                       
                                                                                
 ────────────────────────────────────────────────────────────────────────────── 

Resume this session with:
  hermes --resume 20261008_132358_5b415c -p architect-critic-astra
  hermes -c "Review goals plugin design blockers" -p architect-critic-astra

Session:        20261008_132358_5b415c
Title:          Review goals plugin design blockers
Duration:       2m 20s
Messages:       25 (1 user, 23 tool calls)
