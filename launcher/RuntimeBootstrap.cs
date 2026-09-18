using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Diagnostics;

internal static class RuntimeBootstrap {
    internal static async Task<string> Prepare(string root, string profile, Action<string> report, CancellationToken cancel) {
        if(Array.IndexOf(SetupWindow.Profiles,profile)<0)throw new ArgumentException("Unknown runtime");
        bool amd=profile=="rocm";
        string version=amd?"3.12.10":"3.14.3";
        string hash=amd?"8649692de846c56a7189d6dae5c322ab20deb1b5908b6f39426b62a36f39415d":"ec781bb03f9638d136b24da7c83b4db1652ce767848aa856a30bb87cfdb1abe4";
        string owned=Path.Combine(root,".runtime");
        string directory=Path.Combine(owned,"profiles",profile,"python");
        string archive=Path.Combine(owned,"downloads","python","python-"+version+"-amd64.zip");
        string url="https://www.python.org/ftp/python/"+version+"/python-"+version+"-amd64.zip";
        Action<string,string,double?> emit=(stage,detail,fraction)=>report("SETUP "+new JavaScriptSerializer().Serialize(new { stage=stage,detail=detail,progress=fraction }));
        Directory.CreateDirectory(Path.GetDirectoryName(archive));
        if(File.Exists(archive)) {
            try { await Verify(archive,hash,cancel); }
            catch(InvalidDataException) { File.Delete(archive); }
        }
        if(!File.Exists(archive)) {
            emit("Downloading Python",url,0);
            ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
            string partial=archive+".partial";
            bool complete=false;
            if(File.Exists(partial)) {
                try { await Verify(partial,hash,cancel); complete=true; }
                catch(InvalidDataException) { }
            }
            if(!complete) await Task.Run(()=>{
                long offset=File.Exists(partial)?new FileInfo(partial).Length:0;
                var request=(HttpWebRequest)WebRequest.Create(url);
                if(offset>0)request.AddRange(offset);
                using(cancel.Register(()=>request.Abort())) {
                HttpWebResponse response;
                try { response=(HttpWebResponse)request.GetResponse(); }
                catch(WebException error) {
                    var failed=error.Response as HttpWebResponse;
                    if(failed==null || failed.StatusCode!=HttpStatusCode.RequestedRangeNotSatisfiable)throw;
                    failed.Dispose();
                    offset=0;
                    request=(HttpWebRequest)WebRequest.Create(url);
                    response=(HttpWebResponse)request.GetResponse();
                }
                using(response) {
                if(response.StatusCode!=HttpStatusCode.PartialContent)offset=0;
                else if(!(response.Headers["Content-Range"]??"").StartsWith("bytes "+offset+"-"))throw new InvalidDataException("Invalid download resume range");
                long total=response.ContentLength>0?offset+response.ContentLength:0;
                long received=offset;
                if(offset>0)emit("Resuming Python",String.Format("Continuing from {0:F1} MB",offset/1048576.0),total>0?(double?)offset/total:null);
                using(var input=response.GetResponseStream())
                using(var output=new FileStream(partial,offset>0?FileMode.Append:FileMode.Create,FileAccess.Write)) {
                var clock=Stopwatch.StartNew();
                long lastReport=0;
                byte[] buffer=new byte[262144];
                int count;
                while((count=input.Read(buffer,0,buffer.Length))>0) {
                    cancel.ThrowIfCancellationRequested();
                    output.Write(buffer,0,count);
                    received+=count;
                    if(clock.ElapsedMilliseconds-lastReport<250 && received!=total)continue;
                    lastReport=clock.ElapsedMilliseconds;
                    double speed=(received-offset)/Math.Max(.001,clock.Elapsed.TotalSeconds);
                    double? fraction=total>0?(double?)received/total:null;
                    string detail=String.Format("{0:F1} / {1:F1} MB ({2:P0}) | {3:F1} MB/s",received/1048576.0,total/1048576.0,fraction??0,speed/1048576.0);
                    if(total>0 && speed>0) {
                        var remaining=TimeSpan.FromSeconds(Math.Max(0,(total-received)/speed));
                        detail+=String.Format(" | about {0}m {1:D2}s left",(int)remaining.TotalMinutes,remaining.Seconds);
                    }
                    emit("Downloading Python",detail,fraction);
                }
                if(total>0 && received<total)throw new IOException("Download interrupted. Resume setup to keep downloading from the saved progress.");
                }
                }
                }
            },cancel);
            cancel.ThrowIfCancellationRequested();
            try { await Verify(archive+".partial",hash,cancel); }
            catch(InvalidDataException) { File.Delete(partial); throw; }
            File.Move(archive+".partial",archive);
        }
        emit("Verifying Python","Checking the downloaded runtime",null);
        await Verify(archive,hash,cancel);
        string python=Path.Combine(directory,"python.exe");
        if(!File.Exists(python) || !File.Exists(Path.Combine(directory,".unpacked"))) {
            emit("Unpacking Python","Preparing the application runtime",null);
            await Task.Run(()=>{
                string prefix=Path.GetFullPath(directory).TrimEnd('\\')+"\\";
                using(var zip=ZipFile.OpenRead(archive)) {
                    int count=0;
                    foreach(var entry in zip.Entries) {
                        cancel.ThrowIfCancellationRequested();
                        string target=Path.GetFullPath(Path.Combine(directory,entry.FullName));
                        if(!target.StartsWith(prefix,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Unsafe archive path");
                        if(entry.Name.Length==0)Directory.CreateDirectory(target);
                        else {
                            Directory.CreateDirectory(Path.GetDirectoryName(target));
                            entry.ExtractToFile(target,true);
                        }
                        count++;
                        if(count%100==0)emit("Unpacking Python",count+" of "+zip.Entries.Count+" files",(double)count/zip.Entries.Count);
                    }
                }
                File.WriteAllText(Path.Combine(directory,".unpacked"),version);
            },cancel);
        }
        return python;
    }

    private static Task Verify(string file,string expected,CancellationToken cancel) {
        return Task.Run(()=>{
            cancel.ThrowIfCancellationRequested();
            using(var stream=File.OpenRead(file))using(var sha=SHA256.Create()) {
                string actual=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
                if(actual!=expected)throw new InvalidDataException("Python download failed verification. Retry setup to download a verified copy.");
            }
        },cancel);
    }
}
