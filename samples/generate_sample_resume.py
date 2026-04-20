"""
Generates sample_resume.pdf -- a realistic fictional resume for testing
the Resume Match Scorer app. Run once: python3 generate_sample_resume.py
"""
from fpdf import FPDF, XPos, YPos

class ResumePDF(FPDF):
    def header(self):
        pass

pdf = ResumePDF(format="Letter")
pdf.add_page()
pdf.set_margins(18, 16, 18)
pdf.set_auto_page_break(auto=True, margin=15)

def nl(text="", h=5, font="Helvetica", size=10, style="", color=(0,0,0)):
    pdf.set_font(font, style, size)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

def cell(text, w=0, h=5, font="Helvetica", size=10, style="", color=(0,0,0), fill=False):
    pdf.set_font(font, style, size)
    pdf.set_text_color(*color)
    pdf.cell(w, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=fill)
    pdf.set_text_color(0, 0, 0)

def section(title):
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(220, 230, 255)
    pdf.cell(0, 7, "  " + title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
    pdf.ln(2)

def bullet(text, indent=8):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(pdf.get_x() + indent)
    pdf.multi_cell(0, 5, "-  " + text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

def job_header(title, company, dates, location):
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, company + "  |  " + location + "  |  " + dates,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)

# ---- Name & Contact --------------------------------------------------------
pdf.set_font("Helvetica", "B", 22)
pdf.cell(0, 10, "Jordan M. Rivera", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font("Helvetica", "", 10)
pdf.set_text_color(80, 80, 80)
pdf.cell(0, 5, "Grand Rapids, MI  |  jrivera@email.com  |  (616) 555-0192",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.ln(4)

# ---- Education -------------------------------------------------------------
section("EDUCATION")
pdf.set_font("Helvetica", "B", 10)
pdf.cell(0, 5, "Bachelor of Science - Computer Science",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_font("Helvetica", "", 10)
pdf.cell(0, 5, "Grand Valley State University, Allendale, MI  |  May 2021  |  GPA: 3.7 / 4.0",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(3)

# ---- Experience ------------------------------------------------------------
section("EXPERIENCE")

job_header("Network Engineer", "Midwest Data Systems", "Jun 2021 - Present", "Grand Rapids, MI")
bullet("Design and maintain enterprise LAN/WAN infrastructure supporting 2,000+ endpoints")
bullet("Configure and manage Cisco routers and switches across 8 regional sites")
bullet("Implemented SD-WAN solution reducing WAN costs by 30%")
bullet("Deploy and maintain firewalls (Fortinet, Palo Alto) and VPN tunnels")
bullet("Monitor network health with SNMP, NetFlow, and SolarWinds; respond to incidents")
bullet("Automate provisioning with Python and Ansible; managed Terraform for cloud infra")
bullet("Maintain BGP and OSPF routing across MPLS backbone")
pdf.ln(3)

job_header("IT Infrastructure Intern", "Spectrum Health", "May 2020 - May 2021", "Grand Rapids, MI")
bullet("Assisted deployment of Cisco switches and wireless access points")
bullet("Performed Wireshark packet analysis to diagnose network latency issues")
bullet("Configured VLANs, DHCP, and DNS for new office buildout")
bullet("Documented network topology and maintained IPAM records")
pdf.ln(3)

# ---- Technical Skills ------------------------------------------------------
section("TECHNICAL SKILLS")
skills = [
    ("Protocols",      "TCP/IP, BGP, OSPF, MPLS, VPN, VLAN, SD-WAN, DNS, DHCP, SNMP, NetFlow, IPv4/IPv6"),
    ("Hardware",       "Cisco, Juniper, Fortinet, Palo Alto, F5 load balancers, routers, switches, firewall"),
    ("Tools",          "Wireshark, SolarWinds, Nmap, Nagios, Ansible, Terraform"),
    ("Cloud",          "AWS, Azure, GCP, hybrid cloud networking"),
    ("Languages",      "Python, Bash, PowerShell"),
    ("Security",       "Firewall management, VPN, TLS/SSL, IDS/IPS, CISSP (in progress)"),
    ("Systems",        "Linux, Windows Server, Active Directory, VMware"),
]
for label, val in skills:
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(38, 5, label + ":", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, val, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(2)

# ---- Certifications --------------------------------------------------------
section("CERTIFICATIONS")
bullet("Cisco Certified Network Associate (CCNA) - 2022")
bullet("CompTIA Network+ - 2021")
bullet("AWS Certified Cloud Practitioner - 2023")
pdf.ln(2)

# ---- Activities ------------------------------------------------------------
section("ACTIVITIES & LEADERSHIP")
bullet("President, GVSU Cybersecurity Club (2020-2021) - organized CTF competitions and speaker events")
bullet("Volunteer, West Michigan Tech Volunteers - IT support for local nonprofits")
bullet("Dean's List - 4 semesters")
bullet("Midwest Collegiate Hackathon 2020 - 2nd place, network security track")
pdf.ln(2)

pdf.output("sample_resume.pdf")
print("Generated sample_resume.pdf")
