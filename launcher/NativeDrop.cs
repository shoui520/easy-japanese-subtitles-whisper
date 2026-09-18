using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using ComData = System.Runtime.InteropServices.ComTypes.IDataObject;

namespace EasySubs {
    // Use Shell file identities before Chromium can materialize virtual files.
    public static class NativeDrop {
        [ComImport, Guid("b63ea76d-1f85-456f-a19c-48159efa858b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellItemArray {
            void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr result);
            void GetPropertyStore(int flags, ref Guid iid, out IntPtr result);
            void GetPropertyDescriptionList(IntPtr key, ref Guid iid, out IntPtr result);
            void GetAttributes(uint flags, uint mask, out uint attributes);
            void GetCount(out uint count);
            void GetItemAt(uint index, out IShellItem item);
            void EnumItems(out IntPtr enumerator);
        }
        [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellItem {
            void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr result);
            void GetParent(out IShellItem parent);
            void GetDisplayName(uint kind, out IntPtr name);
            void GetAttributes(uint mask, out uint attributes);
            void Compare(IShellItem other, uint hint, out int order);
        }
        [DllImport("shell32.dll", PreserveSig=false)]
        private static extern void SHCreateShellItemArrayFromDataObject(ComData data, ref Guid iid, out IShellItemArray items);
        [DllImport("shell32.dll",CharSet=CharSet.Unicode)]
        private static extern uint DragQueryFile(IntPtr drop,uint index,StringBuilder path,uint length);
        [DllImport("ole32.dll")]
        private static extern void ReleaseStgMedium(ref System.Runtime.InteropServices.ComTypes.STGMEDIUM medium);

        private static string[] ReadFileDrop(ComData data) {
            var format=new System.Runtime.InteropServices.ComTypes.FORMATETC {
                cfFormat=15, dwAspect=System.Runtime.InteropServices.ComTypes.DVASPECT.DVASPECT_CONTENT,
                lindex=-1, tymed=System.Runtime.InteropServices.ComTypes.TYMED.TYMED_HGLOBAL
            };
            System.Runtime.InteropServices.ComTypes.STGMEDIUM medium;
            data.GetData(ref format,out medium);
            try {
                uint count=DragQueryFile(medium.unionmember,UInt32.MaxValue,null,0);
                var paths=new List<string>();
                for(uint i=0;i<count;i++) {
                    uint length=DragQueryFile(medium.unionmember,i,null,0);
                    var path=new StringBuilder(checked((int)length+1));
                    if(DragQueryFile(medium.unionmember,i,path,length+1)!=length)throw new InvalidOperationException("Incomplete file path");
                    paths.Add(path.ToString());
                }
                return paths.ToArray();
            } finally { ReleaseStgMedium(ref medium); }
        }

        public static string[] ReadPaths(System.Windows.Forms.IDataObject data) {
            var com = data as ComData;
            if(com == null) throw new InvalidOperationException("Windows did not supply the original file paths. Use Add files or Add folder.");
            if(!data.GetDataPresent("Shell IDList Array",false))return ReadFileDrop(com);
            Guid iid = typeof(IShellItemArray).GUID;
            IShellItemArray items;
            SHCreateShellItemArrayFromDataObject(com, ref iid, out items);
            try {
                uint count; items.GetCount(out count);
                var paths = new List<string>();
                for(uint i=0; i<count; i++) {
                    IShellItem item; items.GetItemAt(i,out item);
                    try {
                        IntPtr name; item.GetDisplayName(0x80058000, out name); // SIGDN_FILESYSPATH
                        try { paths.Add(Marshal.PtrToStringUni(name)); }
                        finally { Marshal.FreeCoTaskMem(name); }
                    } finally { Marshal.ReleaseComObject(item); }
                }
                return paths.ToArray();
            } finally { Marshal.ReleaseComObject(items); }
        }

        public static void Attach(Control control, Action<string[]> dropped, Action<bool> hover, Action<string> error) {
            control.AllowDrop = true;
            DragEventHandler enter = (sender,e) => {
                // Do not request file contents or cause virtual-file extraction.
                bool files=false;
                try { files=e.Data.GetDataPresent("Shell IDList Array",false) || e.Data.GetDataPresent(DataFormats.FileDrop,false); }
                catch(Exception) { }
                e.Effect=files && (e.AllowedEffect & DragDropEffects.Copy)!=0 ? DragDropEffects.Copy : DragDropEffects.None;
                hover(e.Effect!=DragDropEffects.None);
            };
            control.DragEnter += enter;
            control.DragOver += enter;
            control.DragLeave += (sender,e) => hover(false);
            control.DragDrop += (sender,e) => {
                hover(false);
                try {
                    var paths=ReadPaths(e.Data);
                    if(paths.Length==0)throw new InvalidOperationException("No original file paths were supplied.");
                    e.Effect=DragDropEffects.Copy;
                    dropped(paths);
                } catch(Exception) {
                    e.Effect=DragDropEffects.None;
                    error("Windows could not provide the original file paths. Use Add files or Add folder. No temporary copy was added.");
                }
            };
        }
    }
}
