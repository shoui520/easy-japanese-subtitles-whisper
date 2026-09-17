using System;
using System.Reflection;
using System.Windows.Forms;

internal static class SetupWindowSmoke {
    [STAThread]
    private static int Main(string[] args) {
        bool fail=args[1]=="fail", sawFailure=false, timedOut=false, sawProgress=false;
        Application.EnableVisualStyles();
        using(var window=new SetupWindow(args[0])) {
            // Exercise our form without displaying a test window to the user.
            window.ShowInTaskbar=false; window.Opacity=0;
            DateTime deadline=DateTime.UtcNow.AddSeconds(12);
            var timer=new Timer(){Interval=100};
            timer.Tick+=(s,e)=>{
                if(DateTime.UtcNow>deadline){timedOut=true;window.Close();return;}
                var stage=(Label)typeof(SetupWindow).GetField("stage",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                var retry=(Button)typeof(SetupWindow).GetField("retry",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                var progress=(ProgressBar)typeof(SetupWindow).GetField("progress",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                if(progress.Value==50)sawProgress=true;
                if(fail&&stage.Text=="Setup needs attention"&&retry.Enabled){
                    sawFailure=window.DialogResult!=DialogResult.OK;
                    window.Close();
                }
            };
            window.Shown+=(s,e)=>{
                typeof(SetupWindow).GetMethod("Install",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(window,null);
                timer.Start();
            };
            Application.Run(window);timer.Dispose();
            if(timedOut)return 2;
            if(!sawProgress)return 5;
            if(fail)return sawFailure?0:3;
            return window.DialogResult==DialogResult.OK?0:4;
        }
    }
}
