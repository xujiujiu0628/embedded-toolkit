using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Plugins;
using Antmicro.Renode.UserInterface;

[Plugin(Name = "probe3", Description = "gpio probe 3", Version = "0.1", Vendor = "local")]
public sealed class ProbePlugin3 : IDisposable
{
    public ProbePlugin3(Monitor monitor) { }
    public void Dispose() { }
}

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class GpioProbe : IPeripheral, IGPIOSender, IGPIOReceiver, INumberedGPIOOutput
    {
        public GpioProbe()
        {
            Line = new GPIO();
            ConnectionsSource = new Dictionary<int, IGPIO> { { 0, Line } };
        }

        public IDictionary<int, IGPIO> ConnectionsSource { get; private set; }
        public IReadOnlyDictionary<int, IGPIO> Connections { get { return (IReadOnlyDictionary<int, IGPIO>)ConnectionsSource; } }

        [DefaultInterrupt]
        public GPIO Line { get; private set; }

        public IGPIO State { get { return Line; } }

        public void OnGPIO(int number, bool value)
        {
            Console.WriteLine(string.Format("GPIO-IN number={0} value={1}", number, value));
        }

        public void Reset() { }
    }
}
