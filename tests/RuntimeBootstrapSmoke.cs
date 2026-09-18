using System;
using System.Threading;
internal static class RuntimeBootstrapSmoke {
    private static int Main(string[] args) {
        string python=RuntimeBootstrap.Prepare(args[0],args[1],Console.WriteLine,CancellationToken.None).GetAwaiter().GetResult();
        Console.WriteLine("Prepared: "+python);
        return System.IO.File.Exists(python)?0:1;
    }
}
