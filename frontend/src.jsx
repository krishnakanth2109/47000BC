import React,{useEffect,useState} from "react";
import {createRoot} from "react-dom/client";
import {initializeApp,getApps} from "firebase/app";
import {getAuth,inMemoryPersistence,setPersistence,signInWithEmailAndPassword,signOut} from "firebase/auth";
import "./style.css";

async function api(path, options={}){
  const response=await fetch("/api/"+path,options);
  const body=await response.json();
  if(!response.ok) throw Error(typeof body.detail==="string"?body.detail:"Request failed");
  return body;
}
function App(){
  const [user,setUser]=useState(null),[data,setData]=useState(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const refresh=()=>api("dashboard").then(setData).catch(e=>setError(e.message));
  useEffect(()=>{api("me").then(setUser).catch(()=>{});},[]);
  useEffect(()=>{
    if(!user)return;
    refresh();
    const socket=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+"/api/live");
    socket.onmessage=e=>{if(e.data==="refresh")refresh();};
    const timer=setInterval(refresh,15000);
    return ()=>{socket.close();clearInterval(timer);};
  },[user]);
  async function action(fn){
    setBusy(true);setError("");
    try{await fn();}catch(e){setError(e.message);}finally{setBusy(false);}
  }
  async function login(f){
    const config=await api("config");
    if(!config.apiKey)throw Error("Set the Firebase web configuration in .env to sign in.");
    const auth=getAuth(getApps()[0]||initializeApp(config));
    await setPersistence(auth,inMemoryPersistence);
    const result=await signInWithEmailAndPassword(auth,f.get("email"),f.get("password"));
    try{await api("session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:await result.user.getIdToken()})});}
    finally{await signOut(auth);}
    setUser(await api("me"));
  }
  return <main><header><h1>Attendance</h1>{user&&<button onClick={()=>action(async()=>{await api("session",{method:"DELETE"});setUser(null);setData(null);})}>Sign out</button>}</header>
    {error&&<p role="alert">{error}</p>}
    {!user?<section><h2>Administrator sign in</h2><form onSubmit={e=>{e.preventDefault();const f=new FormData(e.target);action(()=>login(f));}}>
      <label>Email<input name="email" type="email" required/></label><label>Password<input name="password" type="password" required/></label><button disabled={busy}>Sign in</button></form></section>:
    <><section><h2>Camera</h2><p>{data?.camera||"Loading…"}</p>{["start","stop"].map(a=><button key={a} disabled={busy} onClick={()=>action(async()=>{await api("camera/"+a,{method:"POST"});await refresh();})}>{a==="start"?"Start camera":"Stop camera"}</button>)}</section>
    <section><h2>Register employee</h2><form onSubmit={e=>{e.preventDefault();const form=e.target;action(async()=>{await api("employees",{method:"POST",body:new FormData(form)});form.reset();await refresh();});}}>
    <label>Employee ID<input required name="id"/></label><label>Name<input required name="name"/></label><label>Face photos (3–10)<input required type="file" multiple accept="image/*" name="photos"/></label><button disabled={busy}>Register</button></form>
    <p>{data?.employees.map(e=>e.name+" ("+e.id+")").join(", ")}</p></section>
    <section><h2>Recent attendance</h2><table><thead><tr>{["Employee","Time","Direction","Capture"].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{data?.events.map(e=><tr key={e.id}><td>{e.name}</td><td>{new Date(e.occurred_at).toLocaleString()}</td><td>{e.direction}</td><td><a href={"/api/events/"+e.id+"/snapshot"} target="_blank" rel="noreferrer">View photo</a></td></tr>)}</tbody></table>{data&&!data.events.length&&<p>No attendance recorded yet.</p>}</section></>}</main>;
}
createRoot(document.getElementById("root")).render(<App/>);
