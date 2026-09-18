using System;
using System.Reflection;
using System.Windows.Forms;

internal static class SetupWindowSmoke {
    [STAThread]
    private static int Main(string[] args) {
        bool fail=args[1]=="fail", sawFailure=false, timedOut=false, sawProgress=false, sawInstall=false, sawLive=false;
        Application.EnableVisualStyles();
        using(var window=new SetupWindow(args[0])) {
            window.PrepareRuntime=(profile,report,token)=>System.Threading.Tasks.Task.FromResult(args[3]);
            var compute=(ComboBox)typeof(SetupWindow).GetField("compute",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
            if(compute.Items.Count!=4)return 7;
            if(args.Length>2)compute.SelectedIndex=Array.IndexOf(SetupWindow.Profiles,args[2]);
            // Exercise our form without displaying a test window to the user.
            window.ShowInTaskbar=false; window.Opacity=0;
            DateTime deadline=DateTime.UtcNow.AddSeconds(45);
            var timer=new Timer(){Interval=100};
            timer.Tick+=(s,e)=>{
                if(DateTime.UtcNow>deadline){timedOut=true;window.Close();return;}
                var stage=(Label)typeof(SetupWindow).GetField("stage",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                var retry=(Button)typeof(SetupWindow).GetField("retry",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                var progress=(ProgressBar)typeof(SetupWindow).GetField("progress",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                if(progress.Value==50)sawProgress=true;
                var detail=(Label)typeof(SetupWindow).GetField("detail",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                var live=(TextBox)typeof(SetupWindow).GetField("liveLog",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(window);
                if(live.ReadOnly && live.Text.Contains("Installing application components"))sawLive=true;
                if(progress.Value==25 && progress.Style==ProgressBarStyle.Continuous &&
                    stage.Text=="Installing application components" && detail.Text.Contains("1 of 4 packages installed") &&
                    detail.Text.Contains("Installing numpy"))sawInstall=true;
                if(fail&&stage.Text=="Setup needs attention"&&retry.Enabled){
                    sawFailure=window.DialogResult!=DialogResult.OK && detail.Text=="Choose a compatible driver or CPU.";
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
            if(!sawInstall)return 6;
            if(!sawLive)return 8;
            if(fail)return sawFailure?0:3;
            return window.DialogResult==DialogResult.OK?0:4;
        }
    }
}
