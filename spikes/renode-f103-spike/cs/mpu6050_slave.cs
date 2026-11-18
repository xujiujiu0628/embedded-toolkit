using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Plugins;
using Antmicro.Renode.UserInterface;

[Plugin(Name = "mpu6050-slave", Description = "MPU6050 I2C slave model for the F103 spike", Version = "0.1", Vendor = "local")]
public sealed class Mpu6050SlavePlugin : IDisposable
{
    public Mpu6050SlavePlugin(Monitor monitor) { }
    public void Dispose() { }
}

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    // MPU6050 最小从机: 地址 0x68, WHO_AM_I(0x75)=0x68, 其余寄存器可读写。
    // 引脚约定 (由平台接线决定): OnGPIO number 0 = SCL, 1 = SDA。
    public class Mpu6050Slave : IPeripheral, IGPIOReceiver, IDoubleWordPeripheral, IKnownSize
    {
        private enum St { Idle, Addr, Reg, Write, Read }

        public Mpu6050Slave()
        {
            Scl = new GPIO();
            Sda = new GPIO();
            regs = new byte[128];
            regs[0x75] = 0x68;
            Reset();
        }

        public long Size { get { return 0x100; } }

        public uint ReadDoubleWord(long offset) { return 0; }

        public void WriteDoubleWord(long offset, uint value) { }

        public IGPIOReceiver Host { get; set; }

        private void DriveLow()
        {
            Sda.Set(false);
        }

        private void Release()
        {
            Sda.Set(true);
        }

        private void SetSda(bool level)
        {
            if(level) { Release(); } else { DriveLow(); }
        }

        public GPIO Scl { get; private set; }
        public GPIO Sda { get; private set; }

        public void Reset()
        {
            state = St.Idle;
            bitIndex = 0;
            shift = 0;
            regPtr = 0;
            reading = false;
            sclHigh = false;
            sdaHigh = true;
            Release();
        }

        public void OnGPIO(int number, bool value)
        {
            if(number == 0)
            {
                OnScl(value);
            }
            else if(number == 1)
            {
                OnSda(value);
            }
        }

        private void OnSda(bool value)
        {
            if(sclHigh && sdaHigh && !value)
            {
                StartCondition();
            }
            else if(sclHigh && !sdaHigh && value)
            {
                StopCondition();
            }
            sdaHigh = value;
            if(ackHeld && value)
            {
                DriveLow();
            }
        }

        private void StartCondition()
        {
            Console.WriteLine("SLAVE start");
            state = St.Addr;
            bitIndex = 0;
            ackHeld = false;
            shift = 0;
            reading = false;
            Release();
        }

        private void StopCondition()
        {
            state = St.Idle;
            bitIndex = 0;
            reading = false;
            Release();
        }

        private void OnScl(bool value)
        {
            if(value == sclHigh)
            {
                return;
            }
            if(value)
            {
                OnSclRising();
            }
            else
            {
                OnSclFalling();
            }
            sclHigh = value;
        }

        private void OnSclRising()
        {
            if(state == St.Idle)
            {
                return;
            }
            if(reading)
            {
                if(bitIndex == 8)
                {
                    bool masterAck = !sdaHigh;
                    if(masterAck)
                    {
                        bitIndex = 0;
                        AdvanceReadPointer();
                    }
                    else
                    {
                        StopCondition();
                    }
                }
                return;
            }
            if(bitIndex < 8)
            {
                shift = (byte)((shift << 1) | (sdaHigh ? 1 : 0));
                bitIndex++;
                if(bitIndex == 8)
                {
                    HandleByte();
                }
            }
        }

        private void OnSclFalling()
        {
            if(state == St.Idle)
            {
                return;
            }
            if(reading)
            {
                if(bitIndex < 8)
                {
                    bool bit = ((regs[regPtr & 0x7F] >> (7 - bitIndex)) & 1) != 0;
                    SetSda(bit);
                    bitIndex++;
                }
                else
                {
                    Release();
                }
                return;
            }
            if(bitIndex == 8)
            {
                if(!ackHeld)
                {
                    ackHeld = true;
                }
                else
                {
                    Release();
                    ackHeld = false;
                    bitIndex = 0;
                    shift = 0;
                    if(state == St.Addr && !reading)
                    {
                        state = St.Reg;
                    }
                }
            }
        }

        private void HandleByte()
        {
            byte b = shift;
            Console.WriteLine("SLAVE byte 0x" + b.ToString("X2") + " st=" + (int)state);
            switch(state)
            {
            case St.Addr:
                if((b >> 1) == 0x68)
                {
                    Acknowledge();
                    if((b & 1) == 1)
                    {
                        reading = true;
                        bitIndex = 0;
                    }
                }
                else
                {
                    Nack();
                }
                break;
            case St.Reg:
                regPtr = b & 0x7F;
                Acknowledge();
                state = St.Write;
                break;
            case St.Write:
                regs[regPtr & 0x7F] = b;
                regPtr = (regPtr + 1) & 0x7F;
                Acknowledge();
                break;
            }
        }

        private void AdvanceReadPointer()
        {
            regPtr = (regPtr + 1) & 0x7F;
        }

        private void Acknowledge()
        {
            Console.WriteLine("SLAVE ack-drive");
            DriveLow();
        }

        private void Nack()
        {
            Release();
            state = St.Idle;
        }

        private readonly byte[] regs;
        private St state;
        private int bitIndex;
        private byte shift;
        private int regPtr;
        private bool reading;
        private bool sclHigh;
        private bool sdaHigh;
        private bool driving;
        private bool ackHeld;
    }
}
