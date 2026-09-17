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
        return Program.RuntimeMatches(root)?0:4;
    }
}
