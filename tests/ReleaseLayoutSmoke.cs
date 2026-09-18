using System;
using System.IO;
internal static class ReleaseLayoutSmoke {
    private static int Main(string[] args) {
        string root=Program.ResolveRoot(args[0]);
        if(root!=Path.Combine(Path.GetFullPath(args[0]),"_internal"))return 1;
        if(Program.RuntimeMatches(root))return 2;
        string venv=Path.Combine(root,".runtime","venv");
        Directory.CreateDirectory(venv);
        File.WriteAllText(Path.Combine(venv,"pyvenv.cfg"),"home = C:\\old location\\python\n");
        if(Program.RuntimeMatches(root))return 3;
        File.WriteAllText(Path.Combine(venv,"pyvenv.cfg"),"home = "+Path.Combine(root,".runtime","python")+"\n");
        if(!Program.RuntimeMatches(root))return 4;
        foreach(string profile in SetupWindow.Profiles) {
            File.WriteAllText(Path.Combine(root,".runtime","ready.json"),"{\"profile\":\""+profile+"\"}");
            string selected=Path.Combine(root,".runtime","profiles",profile);
            Directory.CreateDirectory(Path.Combine(selected,"venv"));
            File.WriteAllText(Path.Combine(selected,"venv","pyvenv.cfg"),"home = "+Path.Combine(selected,"python")+"\n");
            if(Program.RuntimeDirectory(root)!=selected || !Program.RuntimeMatches(root))return 5;
        }
        return 0;
    }
}
