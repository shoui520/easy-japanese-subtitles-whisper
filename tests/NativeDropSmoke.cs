using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.IO;
using ComData = System.Runtime.InteropServices.ComTypes.IDataObject;

namespace EasySubs.Tests {
public static class NativeDropSmoke {
    [DllImport("shell32.dll",CharSet=CharSet.Unicode,PreserveSig=false)]
    static extern void SHParseDisplayName(string name,IntPtr context,out IntPtr pidl,uint mask,out uint attributes);
    [DllImport("shell32.dll")] static extern uint ILGetSize(IntPtr pidl);
    static DataObject ShellData(string[] paths) {
        var pidls=new IntPtr[paths.Length];
        try {
            for(int i=0;i<paths.Length;i++) {
                uint attributes;
                try { SHParseDisplayName(paths[i],IntPtr.Zero,out pidls[i],0,out attributes); }
                catch(Exception error) { Console.WriteLine("Shell fixture could not parse: "+paths[i]); throw new Exception("Shell fixture could not parse: "+paths[i],error); }
            }
            // Desktop-relative CIDA supports selections spanning different drives.
            var stream=new MemoryStream(); var writer=new BinaryWriter(stream);
            writer.Write((uint)pidls.Length);
            uint offset=(uint)(4*(pidls.Length+2));
            writer.Write(offset); offset+=2;
            foreach(var pidl in pidls) { writer.Write(offset); offset+=ILGetSize(pidl); }
            writer.Write((ushort)0); // empty parent PIDL = desktop
            foreach(var pidl in pidls) {
                var bytes=new byte[ILGetSize(pidl)]; Marshal.Copy(pidl,bytes,0,bytes.Length); writer.Write(bytes);
            }
            stream.Position=0;
            var data=new DataObject(); data.SetData("Shell IDList Array",false,stream);
            return data;
        } finally {
            foreach(var pidl in pidls)if(pidl!=IntPtr.Zero)Marshal.FreeCoTaskMem(pidl);
        }
    }
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr GetProp(IntPtr hwnd,string name);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr data);
    delegate bool EnumProc(IntPtr hwnd,IntPtr data);
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int x,y; }
    [ComImport, Guid("00000122-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface DropTarget {
        [PreserveSig] int DragEnter(ComData data,uint keys,Point point,ref uint effect);
        [PreserveSig] int DragOver(uint keys,Point point,ref uint effect);
        [PreserveSig] int DragLeave();
        [PreserveSig] int Drop(ComData data,uint keys,Point point,ref uint effect);
    }
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int DropCall(IntPtr self,IntPtr data,uint keys,Point point,ref uint effect);
    public static void Test(Control control,string[] paths) {
        var fileDrop=new DataObject(); fileDrop.SetData(DataFormats.FileDrop,false,paths);
        Console.WriteLine("Checking CF_HDROP paths");
        if(String.Join("|",paths)!=String.Join("|",EasySubs.NativeDrop.ReadPaths(fileDrop)))throw new Exception("CF_HDROP paths changed");
        Console.WriteLine("Creating Shell drop fixture");
        var data=ShellData(paths);
        Console.WriteLine("Checking Shell paths");
        var decoded=EasySubs.NativeDrop.ReadPaths(data);
        if(String.Join("|",paths)!=String.Join("|",decoded))throw new Exception("Native paths changed");
        IntPtr target=GetProp(control.Handle,"OleDropTargetInterface");
        Console.WriteLine("Control target: "+target);
        EnumChildWindows(control.Handle,(hwnd,arg)=>{
            IntPtr child=GetProp(hwnd,"OleDropTargetInterface");
            if(child!=IntPtr.Zero) { Console.WriteLine("Child target: "+child); target=child; }
            return true;
        },IntPtr.Zero);
        if(target==IntPtr.Zero)throw new Exception("No OLE drop target registered");
        IntPtr vtable=Marshal.ReadIntPtr(target);
        var enter=(DropCall)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(vtable,3*IntPtr.Size),typeof(DropCall));
        var drop=(DropCall)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(vtable,6*IntPtr.Size),typeof(DropCall));
        IntPtr nativeData=Marshal.GetComInterfaceForObject(data,typeof(ComData));
        try {
            uint effect=1;
            Marshal.ThrowExceptionForHR(enter(target,nativeData,0,new Point(),ref effect));
            if(effect!=1)throw new Exception("Registered OLE target rejected native file drop: "+effect);
            Marshal.ThrowExceptionForHR(drop(target,nativeData,0,new Point(),ref effect));
            if(effect!=1)throw new Exception("Registered OLE target did not accept drop");
        } finally { Marshal.Release(nativeData); }
    }
}
}
