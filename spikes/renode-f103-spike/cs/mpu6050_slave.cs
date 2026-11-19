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
    // 逐事件打点: 主控寄存器层 / 端口层 / 从机收包层 / 从机采样层共用一条序号流,
    // 便于把"固件写了什么"和"从机看到什么"按时间对齐。
    public static class BusLog
    {
        private static long seq;

        // 初始化段(探测 + 6 条配置写 ≈ 1600 条)必须留够; 之后固件进入 100Hz
        // 采样循环, 不封顶会把 3 秒跑成 20 万行, 还会把 RTT 输出冲掉。
        // 可从 resc 里改: BusLog.Limit = <n>
        public static long Limit = 2600;

        public static void E(string layer, string msg)
        {
            if(seq >= Limit)
            {
                return;
            }
            if(seq == Limit - 1)
            {
                Console.WriteLine("[LOG CAPPED at " + Limit + " events]");
            }
            Console.WriteLine("[" + (seq++).ToString("D6") + "] " + layer + " " + msg);
        }
    }

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
            // burst 核对用图案: 0x3B..0x48 = ACCEL_XOUT_H..GYRO_ZOUT_L 共 14 字节,
            // 每字节互不相同且非零, 便于把"错位"和"错值"分开。
            for(var i = 0; i < 14; i++)
            {
                regs[0x3B + i] = (byte)(0x10 + i);
            }
            Reset();
        }

        public long Size { get { return 0x100; } }

        public uint ReadDoubleWord(long offset) { return 0; }

        public void WriteDoubleWord(long offset, uint value) { }

        public IGPIOReceiver Host { get; set; }
        public IBusController Bus { get; set; }
        public OpenDrainF1Port Port { get; set; }

        // 只读观察口: 用于打点时不参与驱动 (Port 留空, 靠 resc 里的 Sda.Connect)。
        // IDR 读的就是端口 State[], 所以这里等价于"主控此刻会读到什么"。
        public OpenDrainF1Port DiagPort { get; set; }

        // 故障注入旋钮: 第 N 次读事务(含 Init 里探测那次)对地址字节回 NACK。
        // 0 = 关闭(默认)。可从 resc/环境变量设置, 见 i2c_test.resc。
        public int FailBurstAt { get; set; }

        // 持续故障注入: 第 N 次读事务及以后都回 NACK(0 = 关闭)。
        public int FailFromBurst { get; set; }

        // 已发生的读事务次数(探测 + 每次 burst 各算一次), 用于核对注入是否落地。
        public int ReadTransactions { get { return readTransactions; } }

        // 实际注入过的 NACK 次数(0/1), 用于区分"注入没发生"与"固件没反应"。
        public int InjectedNacks { get { return injectedNacks; } }

        // 打点上限的运行时设置口: IronPython 里 import 不到运行时编译的 BusLog 类型,
        // 只能经实例方法转一手。
        public void SetLogLimit(long limit)
        {
            BusLog.Limit = limit;
        }

        private string PortBits()
        {
            if(DiagPort == null)
            {
                return "n/a";
            }
            return "SCL=" + (DiagPort.PinState(10) ? 1 : 0) + ",SDA=" + (DiagPort.PinState(11) ? 1 : 0)
                + ",IDR=0x" + DiagPort.ReadDoubleWord(0x08).ToString("X4");
        }

        private void DriveLow()
        {
            drivingLow = true;
            selfDrive = true;
            try
            {
                BusLog.E("SLV", "drive SDA=0");
                Sda.Set(false);
                if(Port != null) { Port.SlaveDrive(11, false); }
            }
            finally
            {
                selfDrive = false;
            }
        }

        private void Release()
        {
            drivingLow = false;
            selfDrive = true;
            try
            {
                BusLog.E("SLV", "release SDA");
                Sda.Set(true);
                if(Port != null) { Port.SlaveDrive(11, true); }
                // 释放后线路电平由主控决定(端口已把主控原来的值还回来)。
                sdaHigh = (DiagPort == null) || DiagPort.PinState(11);
            }
            finally
            {
                selfDrive = false;
            }
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
            readAckPhase = 0;
            readAckPending = false;
            sclHigh = false;
            sdaHigh = true;
            Release();
        }

        public void OnGPIO(int number, bool value)
        {
            BusLog.E("SLV", "recv pin=" + number + " val=" + (value ? 1 : 0)
                + " selfDrive=" + (selfDrive ? 1 : 0)
                + " scl=" + (sclHigh ? 1 : 0) + " sda=" + (sdaHigh ? 1 : 0)
                + " st=" + state + " bit=" + bitIndex + " ackHeld=" + (ackHeld ? 1 : 0)
                + " idr=" + PortBits());
            if(selfDrive)
            {
                return;
            }
            // 真开漏是"线与": 从机拉低后, 主控再写 1 也拉不高总线。但 Renode 的端口
            // 只有单写者 State[]: SetBitsFromMask 在通知接收者之后会把 State 置回主控
            // 写的值, 覆盖掉从机的 0。所以只要还在拉低, 每收到一个总线事件就重新压低一次,
            // 保证主控读 IDR 时看到的是低(ACK 位 / 读数据位 0)。
            if(drivingLow)
            {
                ReassertLow();
            }
            if(number == 0)
            {
                OnScl(value);
            }
            else if(number == 1)
            {
                OnSda(value);
            }
            // 事件处理完后的线路电平 = 主控下一次读 IDR 会拿到的值。
            BusLog.E("SLV", "post pin=" + number + " val=" + (value ? 1 : 0)
                + " drive=" + (drivingLow ? 1 : 0) + " idr=" + PortBits());
        }

        private void ReassertLow()
        {
            // Sda 自己的 GPIO 也会去重(已为低时再 Set(false) 不通知端口),
            // 先抬高再压低才能把"低"真正送进端口。
            // selfDrive 必须置位, 否则端口回灌的 OnGPIO 会再次进到这里无限递归。
            selfDrive = true;
            try
            {
                Sda.Set(true);
                Sda.Set(false);
            }
            finally
            {
                selfDrive = false;
            }
        }

        private void OnSda(bool value)
        {
            // 我们从机在拉低时, 线上就是低(开漏线与), 主控写 1 也拉不高。
            // 此时主控的写不构成 START/STOP 边沿。
            if(!drivingLow)
            {
                if(sclHigh && sdaHigh && !value)
                {
                    BusLog.E("SLV", "START detected");
                    StartCondition();
                }
                else if(sclHigh && !sdaHigh && value)
                {
                    BusLog.E("SLV", "STOP detected");
                    StopCondition();
                }
                sdaHigh = value;
            }
            else
            {
                sdaHigh = false;
            }
        }

        private void StartCondition()
        {
            BusLog.E("SLV", "start");
            state = St.Addr;
            bitIndex = 0;
            ackHeld = false;
            shift = 0;
            reading = false;
            readAckPhase = 0;
            readAckPending = false;
            Release();
        }

        private void StopCondition()
        {
            state = St.Idle;
            bitIndex = 0;
            reading = false;
            readAckPhase = 0;
            readAckPending = false;
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
                // 第 8 个数据位是在第 8 个下降沿驱动、由下一个上升沿采样的。
                // 主控的 ACK/NACK 要再下一拍才出现, 所以不能在"驱动完 8 位后的第一个
                // 上升沿"就判 —— 那一拍还在采 bit7, 早了会把这位置成 1。
                if(readAckPending)
                {
                    readAckPending = false;
                    bool masterAck = !sdaHigh;
                    BusLog.E("SLV", "read-byte master-ack=" + (masterAck ? 1 : 0) + " sda=" + (sdaHigh ? 1 : 0));
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
                BusLog.E("SLV", "sample bit" + bitIndex + "=" + (sdaHigh ? 1 : 0)
                    + " -> shift=0x" + shift.ToString("X2"));
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
                // 读方向的地址 ACK 单独占一拍: 第 8 个下降沿继续压住, 主控在第 9 个
                // 上升沿采样 ACK; 第 9 个下降沿才释放并同拍输出第一个数据位。
                // 少了这两拍, 第一个数据位会被主控当 ACK 吃掉, 整个字节左移一位
                // (0x68 被读成 0x10 一类错值)。
                if(readAckPhase == 1)
                {
                    readAckPhase = 2;
                    BusLog.E("SLV", "read-ack held through 9th rise");
                    return;
                }
                if(readAckPhase == 2)
                {
                    readAckPhase = 0;
                    BusLog.E("SLV", "read-ack done, start data bits");
                    Release();
                }
                if(bitIndex < 8)
                {
                    bool bit = ((regs[regPtr & 0x7F] >> (7 - bitIndex)) & 1) != 0;
                    BusLog.E("SLV", "read bit" + bitIndex + "=" + (bit ? 1 : 0)
                        + " reg=0x" + (regPtr & 0x7F).ToString("X2"));
                    SetSda(bit);
                    bitIndex++;
                }
                else
                {
                    // 8 位驱动完: 释放总线, 主控在下一拍发 ACK/NACK。
                    Release();
                    readAckPending = true;
                }
                return;
            }
            if(bitIndex == 8)
            {
                if(!ackHeld)
                {
                    BusLog.E("SLV", "ack-slot SCL fell, hold ACK through next clock");
                    ackHeld = true;
                }
                else
                {
                    BusLog.E("SLV", "ack-slot done, release");
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
            BusLog.E("SLV", "byte 0x" + b.ToString("X2") + " st=" + (int)state);
            switch(state)
            {
            case St.Addr:
                if((b >> 1) == 0x68)
                {
                    if((b & 1) == 1)
                    {
                        // 故障注入: 第 N 次读事务(含探测那次)回 NACK。
                        // FailBurstAt = 单次(第 N 次); FailFromBurst = 持续(第 N 次及以后)。
                        // 用来验固件"读失败不挂死 + 只报一次诊断"的路径。
                        readTransactions++;
                        if((FailBurstAt > 0 && readTransactions == FailBurstAt)
                            || (FailFromBurst > 0 && readTransactions >= FailFromBurst))
                        {
                            injectedNacks++;
                            BusLog.E("SLV", "INJECT NACK on read transaction #" + readTransactions);
                            Nack();
                            break;
                        }
                        reading = true;
                        bitIndex = 0;
                        readAckPhase = 1;
                    }
                    Acknowledge();
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
            BusLog.E("SLV", "ack-drive");
            DriveLow();
        }

        private void Nack()
        {
            BusLog.E("SLV", "nack (no ACK driven)");
            Release();
            state = St.Idle;
        }

        private readonly byte[] regs;
        private St state;
        private int bitIndex;
        private byte shift;
        private int regPtr;
        private bool reading;
        private int readAckPhase;
        private int readTransactions;
        private int injectedNacks;
        private bool readAckPending;
        private bool sclHigh;
        private bool sdaHigh;
        private bool drivingLow;
        private bool ackHeld;
        private bool selfDrive;
        private bool selfWrite;
    }
}


namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    using System.Collections.Generic;
    using Antmicro.Renode.Core;
    using Antmicro.Renode.Peripherals.GPIOPort;

    // STM32F1GPIOPort 在输出模式下丢弃外部驱动 (OnGPIO 直接 return)，导致开漏
    // 从机拉不低总线。这里覆盖成"外部低电平强制拉低、外部高电平不覆盖"，
    // 并给从机一个直接改 State 的入口 (SlaveDrive)。
    public class OpenDrainF1Port : STM32F1GPIOPort
    {
        public OpenDrainF1Port(IMachine machine, List<List<int>> invertedAFPins = null)
            : base(machine, invertedAFPins)
        {
        }

        // 注: STM32F1GPIOPort 的 Read/WriteDoubleWord 是接口实现的 final virtual,
        // 子类覆盖不了 (CS0506)。所以寄存器层打点做不到; 主控写引脚的流走
        // Connections[pin].Set() 无条件扇出, 从机作为接收者能看到全部事件,
        // 判据以从机层 (SLV) 日志为准。

        private static string Bits(uint bits)
        {
            return "SCL=" + (((bits & 0x0400) != 0) ? 1 : 0) + ",SDA=" + (((bits & 0x0800) != 0) ? 1 : 0);
        }

        private ushort StateBits()
        {
            ushort v = 0;
            for(var i = 0; i < 16; i++)
            {
                if(State[i])
                {
                    v |= (ushort)(1 << i);
                }
            }
            return v;
        }

        public bool PinState(int pin)
        {
            return State[pin];
        }

        public void SlaveDrive(int pin, bool level)
        {
            if(pin < 0 || pin >= 16)
            {
                return;
            }
            if(!level)
            {
                if(!saved.ContainsKey(pin))
                {
                    saved[pin] = State[pin];
                }
                State[pin] = false;
                Connections[pin].Set(false);
                BusLog.E("PORT", "slaveDrive pin=" + pin + " low (own saved, st=" + Bits(StateBits()) + ")");
            }
            else
            {
                bool own = true;
                if(saved.TryGetValue(pin, out var v))
                {
                    own = v;
                    saved.Remove(pin);
                }
                State[pin] = own;
                Connections[pin].Set(own);
                BusLog.E("PORT", "slaveDrive pin=" + pin + " release own=" + (own ? 1 : 0)
                    + " st=" + Bits(StateBits()));
            }
        }

        public override void OnGPIO(int number, bool value)
        {
            if(number < 0 || number >= 16)
            {
                return;
            }
            if(!value)
            {
                State[number] = false;
                Connections[number].Set(false);
                BusLog.E("PORT", "extDrive pin=" + number + " low st=" + Bits(StateBits()));
                return;
            }
            bool own;
            if(saved.TryGetValue(number, out var v))
            {
                own = v;
                saved.Remove(number);
            }
            else
            {
                own = true;
            }
            State[number] = own;
            Connections[number].Set(own);
            BusLog.E("PORT", "extDrive pin=" + number + " high own=" + (own ? 1 : 0)
                + " st=" + Bits(StateBits()));
        }

        private readonly Dictionary<int, bool> saved = new Dictionary<int, bool>();
    }
}
